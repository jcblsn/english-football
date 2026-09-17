"""Collection into a temporary capture workspace, and the canonical coverage audit."""

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from epl_forecast.data import api_football as api
from epl_forecast.data import football_data, fpl, understat_ingest
from epl_forecast.data.capture import (
    Fetcher,
    SourceAccessError,
)
from epl_forecast.data.sources import (
    ENTRY_SOURCE_COMPETITIONS,
    season_name,
    source_url,
)
from epl_forecast.datasets import Dataset
from epl_forecast.storage import R2Store, write_json

FIXTURE_REFRESH_SECONDS = 3600
FIXTURE_DETAIL_REFRESH_SECONDS = 15 * 60
# Clubs announce starting lineups about an hour before kickoff; capture them before kickoff.
LINEUP_WINDOW = timedelta(minutes=75)
LINEUP_REFRESH_SECONDS = 9 * 60
IN_PLAY_REFRESH_SECONDS = 60 * 60
XG_SETTLEMENT_AGE = timedelta(days=3)
MARKET_READINESS_HORIZON = timedelta(days=7)
PERSONNEL_READINESS_HORIZON = timedelta(days=6)


def normalized_request(fetcher, endpoint, params=None, *, retained=True, **kwargs):
    """Return the response body; with retained=False, normalize only a new response."""
    record, body = api.request(fetcher, endpoint, params, **kwargs)
    if retained or fetcher.is_new(record):
        api.normalize(record, body, fetcher.root)
    return body


def same_named_player(left, right):
    """Two names that cannot describe distinct players on the same team sheet.

    Stricter than the shirt-number fallback in ingestion, which already knows the
    two records share a squad number. Here the surname must match exactly and one
    given name must abbreviate the other, so teammates who merely share a middle
    name or a surname are not reported as contradictions.
    """
    a, b = api.name_words(left), api.name_words(right)
    if not a or not b or a[-1] != b[-1]:
        return False
    return a[0].startswith(b[0]) or b[0].startswith(a[0])


def captured_player_histories(manifests):
    """API IDs whose transfer/sidelined history has its own captured response."""
    captured = {"transfers": set(), "sidelined": set()}
    for manifest in manifests:
        context = manifest["request"]["context"]
        endpoint = context.get("endpoint")
        if endpoint in captured and "player" in context:
            captured[endpoint].add(int(context["player"]))
    return captured


def starter_counts(data):
    counts = defaultdict(dict)
    for row in data.rows(
        "SELECT match_id, team_id, count(DISTINCT player_id) AS starters, "
        "count(DISTINCT player_id) FILTER (WHERE minutes IS NOT NULL) AS usable_starters "
        "FROM appearances WHERE starts=1 GROUP BY 1,2"
    ):
        counts[row["match_id"]][row["team_id"]] = row
    return counts


def incomplete_lineup(counts, fixture):
    """Starter detail when a fixture lacks exactly eleven usable starters for each team."""
    sides = counts.get(fixture["match_id"], {})
    teams = [fixture["home_team_id"], fixture["away_team_id"]]
    detail = {t: sides.get(t, {"starters": 0, "usable_starters": 0}) for t in teams}
    unexpected = sorted(set(sides) - set(teams))
    if not unexpected and all(
        d["starters"] == 11 and d["usable_starters"] == 11 for d in detail.values()
    ):
        return None
    return {
        "match_id": fixture["match_id"],
        "competition_id": fixture["competition_id"],
        "season_id": fixture["season_id"],
        "teams": {
            t: {"starters": d["starters"], "usable_starters": d["usable_starters"]}
            for t, d in detail.items()
        },
        "unexpected_teams": unexpected,
    }


def identity_contradictions(data):
    """Provider identities that cannot all describe distinct players."""
    report = {
        "unapplied_player_aliases": sorted(
            set(api.PLAYER_ALIASES)
            & {
                r["api_id"]
                for r in data.rows("SELECT DISTINCT api_id FROM players WHERE api_id IS NOT NULL")
            }
        ),
        "chained_player_aliases": sorted(
            set(api.PLAYER_ALIASES) & set(api.PLAYER_ALIASES.values())
        ),
    }
    for column in ("understat_id", "fpl_code"):
        report[f"shared_{column}"] = data.rows(
            f"SELECT {column}, count(DISTINCT player_id) AS players FROM players "
            f"WHERE {column} IS NOT NULL GROUP BY 1 HAVING count(DISTINCT player_id)>1 ORDER BY 1"
        )
    rows = defaultdict(list)
    for row in data.rows(
        "SELECT a.match_id, a.team_id, a.player_id, a.season_id, p.name "
        "FROM appearances a JOIN players p USING(player_id)"
    ):
        rows[(row["match_id"], row["team_id"])].append(row)
    duplicates = []
    for (match_id, team_id), entries in sorted(rows.items()):
        for index, left in enumerate(entries):
            for right in entries[index + 1 :]:
                if same_named_player(left["name"], right["name"]):
                    duplicates.append(
                        {
                            "match_id": match_id,
                            "team_id": team_id,
                            "season_id": left["season_id"],
                            "player_ids": sorted([left["player_id"], right["player_id"]]),
                            "names": [left["name"], right["name"]],
                        }
                    )
    report["same_team_name_collisions"] = duplicates
    return report


def fixture_details_due(fixtures, records, now):
    captured = {}
    for record in records:
        context = record.get("context", {})
        if record["provider"] != "api_football" or context.get("endpoint") != "fixtures":
            continue
        ids = str(context.get("ids", context.get("id", ""))).split("-")
        for value in ids:
            if value:
                fid = int(value)
                observed = datetime.fromisoformat(record["retrieved_at"])
                captured[fid] = max(observed, captured.get(fid, observed))
    selected = []
    for row in fixtures:
        fixture = row["fixture"]
        kickoff = datetime.fromisoformat(fixture["date"])
        previous = captured.get(fixture["id"])
        elapsed = None if previous is None else (now - previous).total_seconds()
        status = fixture["status"]["short"]
        if status in {"FT", "AET", "PEN", "AWD", "WO"}:
            targets = [
                kickoff + timedelta(hours=2),
                kickoff + timedelta(days=1),
                kickoff + timedelta(days=3),
                kickoff + timedelta(days=7),
            ]
            due = any(
                target <= now and (previous is None or previous < target) for target in targets
            )
            due = due and (elapsed is None or elapsed >= FIXTURE_DETAIL_REFRESH_SECONDS)
        elif now < kickoff:
            due = kickoff - LINEUP_WINDOW <= now
            due = due and (elapsed is None or elapsed >= LINEUP_REFRESH_SECONDS)
        else:
            due = now <= kickoff + timedelta(hours=6)
            due = due and (elapsed is None or elapsed >= IN_PLAY_REFRESH_SECONDS)
        if due:
            selected.append(fixture["id"])
    return selected


def collection_readiness(data, now):
    """Non-blocking coverage signals for the inputs whose provider timing can vary."""
    from epl_forecast.personnel import (
        Evidence,
        api_status_value,
        fpl_status_value,
        load_availability_evidence,
        season_ids,
    )

    fixtures = [fixture for fixture in data.fixtures() if fixture["stage"] == "regular"]
    current_season = season_name(now.year - (now.month < 7))
    settled = [
        fixture
        for fixture in fixtures
        if fixture["season_id"] == current_season
        and fixture["status"] == "finished"
        and fixture["kickoff_time"] is not None
        and fixture["kickoff_time"] <= now - XG_SETTLEMENT_AGE
    ]
    xg_teams = {
        row["match_id"]: row["teams"]
        for row in data.rows(
            "SELECT match_id, count(DISTINCT team_id) FILTER "
            "(WHERE expected_goals IS NOT NULL) AS teams FROM team_statistics "
            "WHERE season_id=? GROUP BY match_id",
            [current_season],
        )
    }
    missing_xg = [
        {
            "match_id": fixture["match_id"],
            "competition_id": fixture["competition_id"],
            "kickoff_time": fixture["kickoff_time"].isoformat(),
            "teams_with_xg": xg_teams.get(fixture["match_id"], 0),
        }
        for fixture in settled
        if xg_teams.get(fixture["match_id"], 0) < 2
    ]

    upcoming = [
        fixture
        for fixture in fixtures
        if fixture["competition_id"] == "eng-premier-league"
        and fixture["kickoff_time"] is not None
        and now <= fixture["kickoff_time"] <= now + MARKET_READINESS_HORIZON
    ]
    market_matches = {
        row["match_id"]
        for row in data.rows(
            "SELECT DISTINCT match_id FROM odds WHERE competition_id='eng-premier-league' "
            "AND home_odds IS NOT NULL AND draw_odds IS NOT NULL AND away_odds IS NOT NULL"
        )
    }
    missing_market = [
        {
            "match_id": fixture["match_id"],
            "kickoff_time": fixture["kickoff_time"].isoformat(),
        }
        for fixture in upcoming
        if fixture["match_id"] not in market_matches
    ]

    personnel_matches = {
        fixture["match_id"]
        for fixture in upcoming
        if fixture["kickoff_time"] <= now + PERSONNEL_READINESS_HORIZON
    }
    evidence = Evidence(now, **load_availability_evidence(data, season_ids(now)))
    disagreements = []
    for (match_id, team_id, player_id), rows in sorted(evidence.injuries.items()):
        if match_id not in personnel_matches:
            continue
        fpl = evidence.fpl.get(player_id)
        if fpl is None or fpl["team_id"] != team_id:
            continue
        api_values = sorted({api_status_value(row["status"]) for row in rows}, key=str)
        fpl_value = fpl_status_value(fpl["status"])
        if api_values == [fpl_value]:
            continue
        disagreements.append(
            {
                "match_id": match_id,
                "team_id": team_id,
                "player_id": player_id,
                "api_football_statuses": sorted({row["status"] for row in rows}),
                "fpl_status": fpl["status"],
            }
        )

    return {
        "informational_only": True,
        "status": "available",
        "settled_finished_matches": len(settled),
        "finished_matches_missing_xg": len(missing_xg),
        "finished_matches_missing_xg_detail": missing_xg[:50],
        "upcoming_premier_league_matches": len(upcoming),
        "upcoming_matches_without_market_data": len(missing_market),
        "upcoming_matches_without_market_data_detail": missing_market[:50],
        "personnel_source_disagreements": len(disagreements),
        "personnel_source_disagreement_detail": disagreements[:50],
        "xg_settlement_days": XG_SETTLEMENT_AGE.days,
        "market_horizon_days": MARKET_READINESS_HORIZON.days,
        "personnel_horizon_days": PERSONNEL_READINESS_HORIZON.days,
    }


def collect(root, season=None, store=None):
    now = datetime.now(UTC)
    year = season if season is not None else now.year - (now.month < 7)
    fetcher = Fetcher(root, store=store)
    errors = []

    def attempt(function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (ValueError, SourceAccessError, OSError) as error:
            errors.append(str(error))
            return None

    # A retained response inside its refresh interval was normalized when it was captured.
    def refresh(provider, url, ingest, *, max_age, context):
        if fetcher.reusable(url, max_age):
            return
        response = attempt(fetcher.get, provider, url, context=context, max_age=max_age)
        if response:
            attempt(ingest, root, *response)

    def refresh_api(endpoint, params, *, max_age, context=None):
        if fetcher.reusable(api.url(endpoint, params), max_age):
            return
        response = attempt(api.request, fetcher, endpoint, params, context=context, max_age=max_age)
        if response:
            attempt(api.normalize, *response, root)

    for league, comp in api.LEAGUES.items():
        body = attempt(
            normalized_request,
            fetcher,
            "fixtures",
            {"league": league, "season": year},
            max_age=FIXTURE_REFRESH_SECONDS,
            retained=False,
        )
        if body is None:
            continue
        fixtures = body["response"]
        teams = {r["teams"][side]["id"] for r in fixtures for side in ("home", "away")}
        for team in sorted(teams):
            refresh_api(
                "players/squads",
                {"team": team},
                max_age=86400,
                context={"competition_id": comp, "season_id": season_name(year)},
            )
        page = 1
        while True:
            params = {"league": league, "season": year, "page": page}
            following = api.url("players", {**params, "page": page + 1})
            if fetcher.reusable(api.url("players", params), 7 * 86400) and fetcher.reusable(
                following, 7 * 86400
            ):
                page += 1
                continue
            players = attempt(
                normalized_request,
                fetcher,
                "players",
                params,
                max_age=7 * 86400,
                retained=False,
            )
            if players is None:
                break
            if players["paging"]["current"] != page:
                errors.append(f"Wrong player page for {comp}: expected {page}")
                break
            if page >= players["paging"]["total"]:
                break
            page += 1
        for team in sorted(teams):
            refresh_api(
                "transfers",
                {"team": team},
                max_age=86400 if now.month in (1, 6, 7, 8, 9) else 7 * 86400,
            )
        refresh_api("injuries", {"league": league, "season": year}, max_age=14400)
        refresh_api("standings", {"league": league, "season": year}, max_age=14400)
        selected = fixture_details_due(fixtures, fetcher.records, now)
        for offset in range(0, len(selected), 20):
            refresh_api(
                "fixtures",
                {"ids": "-".join(map(str, selected[offset : offset + 20]))},
                max_age=LINEUP_REFRESH_SECONDS,
            )
    refresh("fpl", fpl.URL, fpl.ingest, max_age=1800, context={"season_id": season_name(year)})
    for division, comp in ENTRY_SOURCE_COMPETITIONS.items():
        context = {
            "season_start": year,
            "season_id": season_name(year),
            "division": division,
            "competition_id": comp["id"],
        }
        refresh(
            "football_data",
            source_url(year, division),
            football_data.ingest,
            max_age=86400,
            context=context,
        )
    refresh(
        "football_data",
        "https://football-data.co.uk/fixtures.csv",
        football_data.ingest,
        max_age=21600,
        context={"kind": "latest_odds", "season_id": season_name(year)},
    )
    refresh(
        "understat",
        f"https://understat.com/getLeagueData/EPL/{year}",
        understat_ingest.ingest,
        max_age=86400,
        context={"kind": "league", "season_start": year},
    )
    data = Dataset(store=store, workspace=root)
    matches = data.rows(
        "SELECT DISTINCT t.match_id, t.source_match_id, f.match_date "
        "FROM team_process t JOIN fixtures f USING(match_id) "
        "WHERE t.source_match_id IS NOT NULL AND t.season_id=? AND "
        "(f.match_date>=? OR NOT EXISTS "
        "(SELECT 1 FROM player_process p WHERE p.match_id=t.match_id))",
        [season_name(year), (now - timedelta(days=8)).date()],
    )
    data.close()
    for match in matches:
        refresh(
            "understat",
            f"https://understat.com/getMatchData/{match['source_match_id']}",
            understat_ingest.ingest,
            max_age=86400,
            context={"kind": "players", "match_id": match["match_id"]},
        )
    try:
        readiness_at = datetime.now(UTC)
        data = Dataset(readiness_at, store=store, workspace=root)
        try:
            readiness = collection_readiness(data, readiness_at)
        finally:
            data.close()
    except Exception as error:
        readiness_at = datetime.now(UTC)
        readiness = {
            "informational_only": True,
            "status": "unavailable",
            "error": str(error),
        }
    usage = fetcher.usage()
    report = {
        "completed_at": readiness_at.isoformat(),
        "status": "partial" if errors else "complete",
        "errors": errors,
        "api_football": usage,
        "readiness": readiness,
    }
    write_json(Path(root) / "audits" / "collection.json", report)
    if usage["calls"]:
        write_json(
            Path(root) / "audits" / "api_football" / f"{now:%Y%m%dT%H%M%SZ}.json",
            {
                "started_at": now.isoformat(),
                "completed_at": report["completed_at"],
                "status": report["status"],
                **usage,
            },
        )
    return report


def audit(store):
    """Check the canonical R2 history and write the coverage report to R2."""
    data = Dataset(store=store)
    try:
        data.verify()
        fixtures = data.fixtures()
        counts = {}
        for f in fixtures:
            key = f"{f['competition_id']}/{f['season_id']}/{f['stage']}"
            counts[key] = counts.get(key, 0) + 1
        report = {
            "audited_at": datetime.now(UTC).isoformat(),
            "fixtures": counts,
            "tables": {
                t: data.rows(f"SELECT count(*) AS n FROM {t}")[0]["n"]
                for t in (
                    "players",
                    "appearances",
                    "memberships",
                    "availability",
                    "transfers",
                    "team_process",
                    "player_process",
                    "odds",
                )
            },
            "unresolved_process_players": data.rows(
                "SELECT count(DISTINCT understat_id) AS n "
                "FROM player_process WHERE player_id IS NULL"
            )[0]["n"],
            "unresolved_fpl_codes": data.rows(
                "SELECT count(DISTINCT fpl_code) AS n "
                "FROM availability_observations WHERE fpl_code IS NOT NULL AND player_id IS NULL "
                "AND retrieved_at=(SELECT max(retrieved_at) FROM availability_observations "
                "WHERE provider='fpl')"
            )[0]["n"],
        }
        report["normalization_issues"] = [
            {"source_sha256": m["request"]["source_sha256"], **issue}
            for m in data.manifests
            for issue in m["request"].get("normalization_issues", [])
        ]
        report["season_coverage"] = data.rows(
            "WITH f AS (SELECT DISTINCT match_id, competition_id, season_id, stage FROM fixtures), "
            "a AS (SELECT DISTINCT match_id FROM appearances) "
            "SELECT competition_id, season_id, "
            "count(*) FILTER (WHERE stage='regular') AS regular_fixtures, "
            "CASE competition_id "
            + " ".join(
                f"WHEN '{c['id']}' THEN {c['matches']}" for c in ENTRY_SOURCE_COMPETITIONS.values()
            )
            + " END AS expected_regular, "
            "count(*) FILTER (WHERE stage<>'regular') AS playoff_fixtures, "
            "count(a.match_id) AS fixtures_with_appearances "
            "FROM f LEFT JOIN a USING(match_id) GROUP BY 1,2 ORDER BY 1,2"
        )
        counts = starter_counts(data)
        incomplete = [
            missing
            for f in fixtures
            if f["stage"] == "regular"
            and f["status"] == "finished"
            and (missing := incomplete_lineup(counts, f)) is not None
        ]
        by_season = {}
        for row in incomplete:
            key = f"{row['competition_id']}/{row['season_id']}"
            counts = by_season.setdefault(key, {"fixtures": 0, "without_any_appearance": 0})
            counts["fixtures"] += 1
            counts["without_any_appearance"] += not any(
                t["starters"] for t in row["teams"].values()
            )
        report["incomplete_starting_lineups"] = {
            "requirement": "Eleven starters with usable identity and minutes for each team",
            "fixtures": len(incomplete),
            "note": "Fixtures without any appearance predate the provider's player-statistics "
            "coverage or await backfill; the rest hold a captured payload that is short, "
            "duplicated or contradictory",
            "by_season": dict(sorted(by_season.items())),
            "examples": [r for r in incomplete if any(t["starters"] for t in r["teams"].values())][
                :50
            ],
        }
        report["identity_contradictions"] = identity_contradictions(data)
        relevant = {
            r["api_id"]
            for r in data.rows(
                "SELECT DISTINCT api_id FROM players p WHERE api_id IS NOT NULL AND "
                "(EXISTS (SELECT 1 FROM memberships m WHERE m.player_id=p.player_id) OR "
                "EXISTS (SELECT 1 FROM appearances a WHERE a.player_id=p.player_id))"
            )
        }
        captured = captured_player_histories(data.manifests)
        report["players_needing_history"] = len(relevant)
        for endpoint in ("transfers", "sidelined"):
            report[f"players_without_{endpoint}_capture"] = len(relevant - captured[endpoint])
        report["archive_status"] = (
            "incomplete"
            if (
                report["players_without_transfers_capture"]
                or report["players_without_sidelined_capture"]
                or report["incomplete_starting_lineups"]["fixtures"]
                or any(report["identity_contradictions"].values())
                or any(
                    r["regular_fixtures"] != r["expected_regular"]
                    for r in report["season_coverage"]
                )
            )
            else "requires_provider_coverage_review"
        )
        store.put_json("audits/coverage.json", report)
        return report
    finally:
        data.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["audit", "query", "ui"])
    parser.add_argument("--cutoff", type=datetime.fromisoformat)
    parser.add_argument(
        "--no-browser", action="store_true", help="Start the UI server without opening a browser"
    )
    parser.add_argument(
        "--sql",
        default=(
            "SELECT competition_id, season_id, count(*) AS matches "
            "FROM analysis.matches GROUP BY 1,2 ORDER BY 1,2"
        ),
    )
    args = parser.parse_args()
    if args.action == "audit":
        print(json.dumps(audit(R2Store.from_environment("R2_DATA_BUCKET")), indent=2, default=str))
        return
    from epl_forecast.analysis import SESSION_DIRECTORY, open_analysis_session, start_ui

    session = open_analysis_session(args.cutoff, session_directory=SESSION_DIRECTORY)
    try:
        if args.action == "query":
            print(json.dumps(session.rows(args.sql), default=str, indent=2))
        else:
            start_ui(session, open_browser=not args.no_browser)
    finally:
        session.close()


if __name__ == "__main__":
    main()
