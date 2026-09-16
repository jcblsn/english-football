"""Small local collection loops shared by backfill and ongoing ingestion."""

import argparse
import json
import tempfile
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from epl_forecast.data import api_football as api
from epl_forecast.data import football_data, fpl, understat_ingest
from epl_forecast.data.capture import (
    Fetcher,
    QuotaReached,
    SourceAccessError,
    WriterBusy,
    writer_lock,
)
from epl_forecast.data.sources import (
    COMPETITIONS,
    ENTRY_SOURCE_COMPETITIONS,
    season_name,
    source_url,
)
from epl_forecast.datasets import Dataset
from epl_forecast.storage import sha256_bytes, write_json

FIXTURE_REFRESH_SECONDS = 3600
FIXTURE_DETAIL_REFRESH_SECONDS = 15 * 60
# Clubs announce starting lineups about an hour before kickoff; capture them before kickoff.
LINEUP_WINDOW = timedelta(minutes=75)
LINEUP_REFRESH_SECONDS = 9 * 60
IN_PLAY_REFRESH_SECONDS = 60 * 60


def normalized_request(fetcher, endpoint, params=None, *, retained=True, **kwargs):
    """Return the response body; with retained=False, normalize only a new response."""
    record, body = api.request(fetcher, endpoint, params, **kwargs)
    if retained or fetcher.is_new(record):
        api.normalize(record, body, fetcher.root)
    return body


def prioritized_players(root, start, end, store=None):
    data = Dataset(root, store=store)
    try:
        return data.rows(
            "WITH seasons AS (SELECT player_id, season_id, competition_id FROM memberships UNION "
            "SELECT player_id, season_id, competition_id FROM appearances), people AS ("
            "SELECT p.player_id, p.api_id, max(s.season_id) AS latest_season, "
            "min(s.competition_id) AS competition_id "
            "FROM players p JOIN seasons s USING(player_id) "
            "WHERE p.api_id IS NOT NULL AND s.season_id>=? AND s.season_id<=? "
            "GROUP BY 1,2) SELECT *, row_number() OVER (PARTITION BY competition_id, latest_season "
            "ORDER BY api_id) AS priority_slot FROM people "
            "ORDER BY latest_season DESC, priority_slot, competition_id",
            [season_name(start), season_name(end)],
        )
    finally:
        data.close()


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


def recent_readiness(root, end, store=None):
    data = Dataset(root, store=store)
    try:
        cohorts = {
            (comp["id"], season_name(year)): {
                "competition_id": comp["id"],
                "season_id": season_name(year),
                "expected_fixtures": comp["matches"],
                "fixtures": 0,
                "finished": 0,
                "finished_with_starter_minutes": 0,
            }
            for comp in COMPETITIONS.values()
            for year in range(end - 3, end + 1)
        }
        counts = starter_counts(data)
        incomplete = []
        for fixture in data.fixtures():
            row = cohorts.get((fixture["competition_id"], fixture["season_id"]))
            if row is None or fixture["stage"] != "regular":
                continue
            row["fixtures"] += 1
            if fixture["status"] != "finished":
                continue
            row["finished"] += 1
            missing = incomplete_lineup(counts, fixture)
            if missing is None:
                row["finished_with_starter_minutes"] += 1
            else:
                incomplete.append(missing)
        captures = captured_player_histories(data.manifests)
        contradictions = identity_contradictions(data)
    finally:
        data.close()
    window = {r["season_id"] for r in cohorts.values()}
    contradictions["same_team_name_collisions"] = [
        c for c in contradictions["same_team_name_collisions"] if c["season_id"] in window
    ]
    rows = list(cohorts.values())
    match_ready = all(
        r["fixtures"] == r["expected_fixtures"]
        and (r["season_id"] == season_name(end) or r["finished"] == r["expected_fixtures"])
        for r in rows
    )
    lineups_ready = all(r["finished"] == r["finished_with_starter_minutes"] for r in rows)
    identity_ready = not any(contradictions.values())
    current = (
        prioritized_players(root, end, end)
        if store is None
        else prioritized_players(root, end, end, store)
    )
    current_ids = {p["api_id"] for p in current}
    report = {
        "audited_at": datetime.now(UTC).isoformat(),
        "window_start": season_name(end - 3),
        "window_end": season_name(end),
        "seasons": rows,
        "ready_for_match_experiments": match_ready,
        "ready_for_player_experiments": match_ready and lineups_ready and identity_ready,
        "starter_requirement": "Eleven starters with usable identity and minutes for each "
        "team in every finished regular fixture",
        "incomplete_starting_lineups": len(incomplete),
        "incomplete_starting_lineup_detail": incomplete[:50],
        "identity_contradictions": contradictions,
        "current_players": len(current),
        "pending_current_player_histories": {
            endpoint: len(current_ids - captured) for endpoint, captured in captures.items()
        },
        "scope": "Input coverage only; not model validation or historical point-in-time evidence",
    }
    write_json(Path(root) / "audits" / "recent_readiness.json", report)
    return report


def backfill(root=Path("data"), start=2010, end=None, max_requests=None):
    now = datetime.now(UTC)
    end = end if end is not None else now.year - (now.month < 7)
    if start > end:
        raise ValueError("Backfill start must not exceed end")
    previous_report = Path(root) / "audits" / "backfill.json"
    if previous_report.exists():
        previous = json.loads(previous_report.read_text())
        if (
            previous.get("status") == "complete"
            and previous.get("start") == start
            and previous.get("end") == end
        ):
            return previous
    fetcher = Fetcher(root, reserve=1000)
    report = {"started_at": now.isoformat(), "start": start, "end": end, "status": "running"}
    initial = len(fetcher.records)

    def get(endpoint, params=None, **kwargs):
        if max_requests is not None and len(fetcher.records) - initial >= max_requests:
            raise QuotaReached("This backfill invocation reached its request budget; resume")
        return normalized_request(fetcher, endpoint, params, historical=True, **kwargs)

    def season_pass(years):
        for year in years:
            for league, comp in api.LEAGUES.items():
                seasons = {s["year"]: s for s in catalog[league]}
                if year not in seasons:
                    continue
                print(f"Backfill {comp} {year}: fixtures, players, injuries", flush=True)
                get("teams", {"league": league, "season": year})
                get("standings", {"league": league, "season": year})
                fixtures = get("fixtures", {"league": league, "season": year})["response"]
                ids = [
                    r["fixture"]["id"]
                    for r in fixtures
                    if r["fixture"]["status"]["short"] in ("FT", "AET", "PEN", "AWD", "WO")
                ]
                for index in range(0, len(ids), 20):
                    selected = ids[index : index + 20]
                    body = get("fixtures", {"ids": "-".join(map(str, selected))})
                    returned = {r["fixture"]["id"]: r for r in body["response"]}
                    for fid in selected:
                        r = returned.get(fid)
                        coverage = seasons[year]["coverage"]["fixtures"]
                        if (
                            r is None
                            or (coverage["lineups"] and not r.get("lineups"))
                            or (coverage["statistics_players"] and not r.get("players"))
                        ):
                            get("fixtures", {"id": fid})
                page = 1
                while True:
                    body = get("players", {"league": league, "season": year, "page": page})
                    if body["paging"]["current"] != page:
                        raise ValueError("API player pagination returned the wrong page")
                    if page >= body["paging"]["total"]:
                        break
                    page += 1
                if seasons[year]["coverage"]["injuries"]:
                    get("injuries", {"league": league, "season": year})

    try:
        report["subscription"] = api.preflight(fetcher)
        catalog = {
            league: get("leagues", {"id": league})["response"][0]["seasons"]
            for league in api.LEAGUES
        }
        recent_start = max(start, end - 3)
        for phase, years, first in [
            ("current", [end], end),
            ("recent", range(end - 1, recent_start - 1, -1), recent_start),
            ("older", range(recent_start - 1, start - 1, -1), start),
        ]:
            report["phase"] = f"{phase}_fixtures_and_players"
            season_pass(years)
            report["phase"] = f"{phase}_player_histories"
            people = prioritized_players(root, first, end)
            report[f"{phase}_players"] = len(people)
            print(
                f"Backfill {phase}: sidelined and transfers for {len(people)} players", flush=True
            )
            for person in people:
                for endpoint in ("sidelined", "transfers"):
                    get(endpoint, {"player": person["api_id"]})
            report[f"{phase}_api_complete"] = True
        for year in range(end, start - 1, -1):
            for division, competition in ENTRY_SOURCE_COMPETITIONS.items():
                record, payload = fetcher.get(
                    "football_data",
                    source_url(year, division),
                    historical=year < end,
                    max_age=86400,
                    context={
                        "season_start": year,
                        "season_id": season_name(year),
                        "division": division,
                        "competition_id": competition["id"],
                    },
                )
                football_data.ingest(root, record, payload)
            if year >= 2014:
                record, payload = fetcher.get(
                    "understat",
                    f"https://understat.com/getLeagueData/EPL/{year}",
                    historical=year < end,
                    max_age=86400,
                    context={"kind": "league", "season_start": year},
                )
                understat_ingest.ingest(root, record, payload)
                data = Dataset(root)
                matches = data.rows(
                    "SELECT DISTINCT match_id, source_match_id FROM team_process "
                    "WHERE source_match_id IS NOT NULL AND season_id=?",
                    [season_name(year)],
                )
                data.close()
                for match in matches:
                    if max_requests is not None and len(fetcher.records) - initial >= max_requests:
                        raise QuotaReached(
                            "This backfill invocation reached its request budget; resume"
                        )
                    record, payload = fetcher.get(
                        "understat",
                        f"https://understat.com/getMatchData/{match['source_match_id']}",
                        historical=True,
                        context={"kind": "players", "match_id": match["match_id"]},
                    )
                    understat_ingest.ingest(root, record, payload)
        report["status"] = "complete"
    except QuotaReached as error:
        report.update(status="paused", reason=str(error))
    except Exception as error:
        report.update(status="failed", reason=str(error))
        raise
    finally:
        report["requests_captured"] = len(fetcher.records) - initial
        report["completed_at"] = datetime.now(UTC).isoformat()
        write_json(Path(root) / "audits" / "backfill.json", report)
        report["recent_readiness"] = recent_readiness(root, end)
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


def collect(root=Path("data"), season=None, store=None):
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
    data = Dataset(root, store=store)
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
    usage = fetcher.usage()
    report = {
        "completed_at": datetime.now(UTC).isoformat(),
        "status": "partial" if errors else "complete",
        "errors": errors,
        "api_football": usage,
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


def normalize(root):
    root = Path(root)
    modules = {"football_data": football_data, "understat": understat_ingest, "fpl": fpl}
    requests = [json.loads(p.read_text()) for p in (root / "requests").glob("*.json")]

    def order(record):
        provider, context = record["provider"], record["context"]
        phase = 0
        if provider == "api_football" and context["endpoint"] in (
            "injuries",
            "sidelined",
            "transfers",
        ):
            phase = 1
        elif provider == "football_data" and context.get("kind") == "latest_odds":
            phase = 2
        elif provider == "understat":
            phase = 2 if context["kind"] == "league" else 3
        elif provider == "fpl":
            phase = 4
        return phase, record["retrieved_at"], record["url"], record["source_sha256"]

    with tempfile.TemporaryDirectory(prefix=".normalize-", dir=root) as temporary:
        staging = Path(temporary)
        understat_context = None
        for record in sorted(requests, key=order):
            payload = (root / record["raw_path"]).read_bytes()
            if sha256_bytes(payload) != record["source_sha256"]:
                raise ValueError(f"Raw capture hash mismatch: {record['raw_path']}")
            if record["provider"] == "efl_rules":
                continue
            if record["provider"] == "api_football":
                if record["context"]["endpoint"] != "status":
                    api.normalize(record, json.loads(payload), staging)
            elif record["provider"] == "understat" and record["context"]["kind"] == "players":
                if understat_context is None:
                    understat_context = understat_ingest.IngestContext(staging)
                understat_ingest.ingest(staging, record, payload, understat_context)
            else:
                modules[record["provider"]].ingest(staging, record, payload)
        data = Dataset(staging)
        try:
            data.verify()
            data.fixtures()
        finally:
            data.close()
        replaced = []
        try:
            for name in ("parquet", "manifests"):
                (staging / name).mkdir(exist_ok=True)
                old = staging / ("previous-" + name)
                if (root / name).exists():
                    (root / name).rename(old)
                replaced.append(name)
                (staging / name).rename(root / name)
        except OSError:
            for name in reversed(replaced):
                if (root / name).exists():
                    (root / name).rename(staging / name)
                old = staging / ("previous-" + name)
                if old.exists():
                    old.rename(root / name)
            raise

    return {"status": "complete", "requests_replayed": len(requests)}


def audit(root):
    data = Dataset(root)
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
        write_json(Path(root) / "audits" / "coverage.json", report)
        return report
    finally:
        data.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["backfill", "collect", "normalize", "audit", "query", "ui"]
    )
    parser.add_argument("--root", type=Path, default=Path("data"))
    parser.add_argument("--start", type=int, default=2010)
    parser.add_argument("--end", type=int)
    parser.add_argument("--max-requests", type=int)
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
    if args.action in {"query", "ui"}:
        from epl_forecast.analysis import open_analysis_session, start_ui

        session = open_analysis_session(args.cutoff, root=args.root)
        try:
            if args.action == "query":
                print(json.dumps(session.rows(args.sql), default=str, indent=2))
            else:
                start_ui(session, open_browser=not args.no_browser)
        finally:
            session.close()
        return
    try:
        with writer_lock(args.root):
            if args.action == "backfill":
                result = backfill(args.root, args.start, args.end, args.max_requests)
            elif args.action == "collect":
                result = collect(args.root, args.end)
            elif args.action == "normalize":
                result = normalize(args.root)
            else:
                result = audit(args.root)
    except WriterBusy as error:
        result = {"status": "skipped", "reason": str(error)}
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
