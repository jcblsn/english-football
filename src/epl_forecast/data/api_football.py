"""API-Football v3 ingestion for English league research."""

import csv
import json
import math
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from epl_forecast.competitions import COMPETITIONS, competition
from epl_forecast.data.capture import SourceAccessError
from epl_forecast.datasets import Dataset, publish
from epl_forecast.schema import fixture_id
from epl_forecast.snapshots import (
    FIXTURE_DETAIL,
    INJURIES,
    SIDELINED,
    SQUAD,
    TEAM_TRANSFERS,
    TRANSFERS,
    fixture_detail_scope,
    injury_scope,
    snapshot,
)

BASE = "https://v3.football.api-sports.io/"
LEAGUES = {c.api_football_league: c.competition_id for c in COMPETITIONS}
ROLES = {
    "G": "GK",
    "D": "DEF",
    "M": "MID",
    "F": "FWD",
    "Goalkeeper": "GK",
    "Defender": "DEF",
    "Midfielder": "MID",
    "Attacker": "FWD",
}

PLAYER_STAT_FIELDS = {
    "rating": ("games", "rating"),
    "passes_total": ("passes", "total"),
    "key_passes": ("passes", "key"),
    "tackles": ("tackles", "total"),
    "interceptions": ("tackles", "interceptions"),
    "duels_total": ("duels", "total"),
    "duels_won": ("duels", "won"),
    "dribbles_attempted": ("dribbles", "attempts"),
    "dribbles_successful": ("dribbles", "success"),
    "fouls_drawn": ("fouls", "drawn"),
    "fouls_committed": ("fouls", "committed"),
}


TEAM_STATISTICS = {
    "expected_goals": ("expected_goals", float),
    "goals_prevented": ("goals_prevented", float),
    "Total Shots": ("shots_total", int),
    "Shots on Goal": ("shots_on_goal", int),
    "Shots off Goal": ("shots_off_goal", int),
    "Blocked Shots": ("shots_blocked", int),
    "Shots insidebox": ("shots_inside_box", int),
    "Shots outsidebox": ("shots_outside_box", int),
    "Corner Kicks": ("corners", int),
    "Offsides": ("offsides", int),
    "Fouls": ("fouls", int),
    "Yellow Cards": ("yellow_cards", int),
    "Red Cards": ("red_cards", int),
    "Goalkeeper Saves": ("goalkeeper_saves", int),
    "Total passes": ("passes_total", int),
    "Passes accurate": ("passes_accurate", int),
    "Ball Possession": ("possession", float),
}


def team_statistic(value, kind):
    """A provider statistic, or None when it is absent rather than zero.

    Percentages arrive as strings; counts the provider did not record arrive as null,
    which is not the same as a recorded zero and is kept unknown.
    """
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip().rstrip("%")
        if not value:
            return None
    try:
        return kind(float(value))
    except (TypeError, ValueError):
        return None


def match_player_statistics(statistics, identity, issues):
    result = {}
    for field, (group, key) in PLAYER_STAT_FIELDS.items():
        raw = (statistics.get(group) or {}).get(key)
        value = None
        if raw is not None:
            try:
                number = float(raw)
                valid = math.isfinite(number) and number >= 0
                valid &= number <= 10 if field == "rating" else number.is_integer()
                if valid:
                    value = number if field == "rating" else int(number)
            except (TypeError, ValueError):
                pass
            if value is None:
                issues.append(
                    {
                        **identity,
                        "field": field,
                        "reported_value": raw,
                        "resolution": "unknown: invalid statistic",
                    }
                )
        result[field] = value
    for total, successful in (
        ("passes_total", "key_passes"),
        ("duels_total", "duels_won"),
        ("dribbles_attempted", "dribbles_successful"),
    ):
        if result[total] is not None and result[successful] is not None:
            if result[successful] > result[total]:
                issues.append(
                    {
                        **identity,
                        "field": [total, successful],
                        "reported_values": [result[total], result[successful]],
                        "resolution": "unknown: successful count exceeds total",
                    }
                )
                result[total] = result[successful] = None
    raw_accuracy = (statistics.get("passes") or {}).get("accuracy")
    result["pass_accuracy"] = str(raw_accuracy) if raw_accuracy is not None else None
    return result


with Path(__file__).with_name("api_player_aliases.csv").open() as stream:
    PLAYER_ALIASES = {int(r["alias_api_id"]): int(r["api_id"]) for r in csv.DictReader(stream)}

# Reviewed fixture records whose result the provider's own retained evidence contradicts.
FIXTURE_DISPUTES = {
    entry["api_id"]: entry
    for entry in json.loads(Path(__file__).with_name("api_fixture_disputes.json").read_text())
}


def canonical_api_id(value):
    if value is None or int(value) <= 0:
        return None
    return PLAYER_ALIASES.get(int(value), int(value))


def player_id(value):
    value = canonical_api_id(value)
    return f"p{value}" if value is not None else None


def name_words(value):
    value = unicodedata.normalize("NFKD", value.lower()).encode("ascii", "ignore").decode()
    return re.findall("[a-z]+", value)


def compatible_name(left, right):
    a, b = name_words(left), name_words(right)
    return bool(
        a and b and (a[0].startswith(b[0]) or b[0].startswith(a[0])) and set(a[1:]) & set(b[1:])
    )


def url(endpoint, params=None):
    return BASE + endpoint + ("?" + urlencode(sorted((params or {}).items())) if params else "")


def request(fetcher, endpoint, params=None, context=None, **kwargs):
    record, payload = fetcher.get(
        "api_football",
        url(endpoint, params),
        context={"endpoint": endpoint, **(params or {}), **(context or {})},
        **kwargs,
    )
    return record, json.loads(payload)


def preflight(fetcher):
    record, body = request(fetcher, "status")
    status = body["response"]
    result = {
        "subscription": status["subscription"],
        "requests": status["requests"],
        "retrieved_at": record["retrieved_at"],
    }
    if not status["subscription"]["active"] or status["requests"]["limit_day"] < 7500:
        raise SourceAccessError("API-Football Pro is required for historical backfill")
    fetcher.remaining = status["requests"]["limit_day"] - status["requests"]["current"]
    return result


def team_registry():
    with Path(__file__).with_name("teams.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    aliases = {r["source_name"]: r["team_id"] for r in rows}
    aliases.update({r["team_name"]: r["team_id"] for r in rows})
    aliases.update(
        {
            "Manchester United": "manchester-united",
            "Manchester City": "manchester-city",
            "Newcastle": "newcastle-united",
            "Wolves": "wolverhampton-wanderers",
            "Tottenham": "tottenham-hotspur",
            "West Brom": "west-bromwich-albion",
            "QPR": "queens-park-rangers",
            "Sheffield Utd": "sheffield-united",
            "Leeds": "leeds-united",
            "Leicester": "leicester-city",
            "Norwich": "norwich-city",
            "Swansea": "swansea-city",
            "Cardiff": "cardiff-city",
            "Hull City": "hull-city",
            "Birmingham": "birmingham-city",
            "Stoke City": "stoke-city",
            "Huddersfield": "huddersfield-town",
            "Bolton": "bolton-wanderers",
            "Blackburn": "blackburn-rovers",
            "Nottingham Forest": "nottingham-forest",
            "Brighton": "brighton-hove-albion",
            "West Ham": "west-ham-united",
            "Wigan": "wigan-athletic",
            "Ipswich": "ipswich-town",
            "Derby": "derby-county",
            "Preston": "preston-north-end",
            "Luton": "luton-town",
            "Milton Keynes Dons": "milton-keynes-dons",
            "Peterborough": "peterborough-united",
            "Charlton": "charlton-athletic",
            "Rotherham": "rotherham-united",
            "Wycombe": "wycombe-wanderers",
            "Accrington ST": "accrington-stanley",
            "Dagenham & Redbridge": "dagenham-redbridge",
            "Sutton Utd": "sutton-united",
        }
    )
    return aliases


def team_key(team, required=False, known=None):
    if team.get("id") is None:
        return None
    if not required:
        return (known or {}).get(team["id"], f"af-team-{team['id']}")
    found = team_registry().get(team["name"])
    if found:
        return found
    if required:
        raise ValueError(f"Unmapped league team: {team['id']} {team['name']}")
    return f"af-team-{team['id']}"


_IDENTITY_KEYS = {}


def identity_keys(root):
    """API-id to canonical team and fixture maps for a published store.

    Injury and transfer payloads are normalized one at a time, and each of them
    publishes team rows, so watching any partition these writes touch makes the cache
    invalidate on every record and a full replay spends its time rebuilding the store.
    The fixture partition is the one input a transfer or injury normalization cannot
    change, so it alone decides when a rebuild is needed; team rows those payloads
    publish are folded back in by `record_identity`, which keeps the map exactly as
    fresh as a rebuild would.
    """
    root = Path(root)
    fixtures = root / "parquet" / "fixtures"
    stamp = fixtures.stat().st_mtime_ns if fixtures.exists() else None
    cached = _IDENTITY_KEYS.get(str(root))
    if cached is not None and cached[0] == stamp:
        return cached[1]
    data = Dataset(workspace=root)
    try:
        keys = (
            {
                r["api_id"]: r["team_id"]
                for r in data.rows("SELECT * FROM teams WHERE api_id IS NOT NULL")
            },
            {
                r["api_id"]: r["match_id"]
                for r in data.rows(
                    "SELECT DISTINCT api_id, match_id FROM fixtures WHERE api_id IS NOT NULL"
                )
            },
        )
    finally:
        data.close()
    _IDENTITY_KEYS[str(root)] = (stamp, keys)
    return keys


def record_identity(root, tables):
    """Fold freshly published team rows into the cached map; latest publication wins."""
    cached = _IDENTITY_KEYS.get(str(Path(root)))
    if cached is None:
        return
    for row in tables.get("teams", ()):
        if row.get("api_id") is not None:
            cached[1][0][row["api_id"]] = row["team_id"]


def source_snapshots(record, body, tables, root):
    """What this response covered, so that a response with no rows is still evidence.

    A scope the provider answered with nothing is not the same as a scope nobody asked
    about, and only a canonical row keeps that difference through compaction.
    """
    context = record["context"]
    endpoint = context["endpoint"]
    if endpoint == "players/squads":
        teams = {team_key(item["team"], True) for item in body["response"]}
        if not teams:
            # The provider answered with no squad. The request still names the team, so the
            # scope is recorded and a reader sees an empty squad instead of the last one.
            resolved = (
                identity_keys(root)[0].get(int(context["team"]))
                if context.get("team") is not None
                else None
            )
            teams = {resolved} if resolved else set()
        members = tables.get("memberships", ())
        return [
            snapshot(
                SQUAD,
                team,
                endpoint=endpoint,
                row_count=sum(1 for row in members if row["team_id"] == team),
                competition_id=context.get("competition_id"),
                season_id=context.get("season_id"),
                team_id=team,
            )
            for team in sorted(teams)
        ]
    if endpoint == "injuries" and context.get("league") is not None:
        competition = LEAGUES[int(context["league"])]
        season = f"{int(context['season'])}-{int(context['season']) + 1}"
        return [
            snapshot(
                INJURIES,
                injury_scope(competition, season),
                endpoint=endpoint,
                row_count=len(tables.get("availability", ())),
                competition_id=competition,
                season_id=season,
            )
        ]
    # A whole-season fixture list carries no lineups, so it never stands in for a capture
    # of one fixture's detail.
    if endpoint == "fixtures" and ("id" in context or "ids" in context):
        fixtures = {
            row["match_id"]: row for row in tables.get("fixtures", ()) if row.get("match_id")
        }
        requested = {
            int(value)
            for value in str(context.get("ids", context.get("id", ""))).split("-")
            if value
        }
        returned = {row.get("api_id") for row in fixtures.values()}
        missing = requested - returned
        if missing:
            fixture_keys = identity_keys(root)[1]
            match_ids = {fixture_keys[value] for value in missing if value in fixture_keys}
            if match_ids:
                data = Dataset(workspace=root)
                try:
                    placeholders = ", ".join("?" for _ in match_ids)
                    known = data.rows(
                        "SELECT DISTINCT match_id, competition_id, season_id, home_team_id, "
                        f"away_team_id FROM fixtures WHERE match_id IN ({placeholders})",
                        sorted(match_ids),
                    )
                finally:
                    data.close()
                fixtures.update({row["match_id"]: row for row in known})
        counts = {}
        for row in tables.get("appearances", ()):
            key = row["match_id"], row["team_id"]
            counts[key] = counts.get(key, 0) + 1
        return [
            snapshot(
                FIXTURE_DETAIL,
                fixture_detail_scope(row["match_id"], team),
                endpoint=endpoint,
                row_count=counts.get((row["match_id"], team), 0),
                competition_id=row["competition_id"],
                season_id=row["season_id"],
                team_id=team,
                match_id=row["match_id"],
            )
            for row in sorted(fixtures.values(), key=lambda item: item["match_id"])
            for team in (row["home_team_id"], row["away_team_id"])
        ]
    # A history is requested for one player or for one club, and the two are separate scopes.
    if endpoint in ("sidelined", "transfers"):
        table = "availability" if endpoint == "sidelined" else "transfers"
        count = len(tables.get(table, ()))
        kind = SIDELINED if endpoint == "sidelined" else TRANSFERS
        if context.get("player") is not None:
            person = player_id(context["player"])
            if person:
                return [snapshot(kind, person, endpoint=endpoint, row_count=count)]
        elif endpoint == "transfers" and context.get("team") is not None:
            team = identity_keys(root)[0].get(int(context["team"]))
            if team:
                return [
                    snapshot(TEAM_TRANSFERS, team, endpoint=endpoint, row_count=count, team_id=team)
                ]
    return []


def normalize(record, body, root):
    endpoint, context = record["context"]["endpoint"], record["context"]
    if endpoint == "fixtures":
        record = {**record, "normalization_version": 2}
    tables = {}
    issues = []
    fixture_keys, team_keys = {}, {}
    if endpoint in ("injuries", "transfers"):
        team_keys, fixture_keys = identity_keys(root)

    def add(table, row):
        tables.setdefault(table, []).append(row)

    for item in body["response"]:
        if endpoint == "leagues":
            league = item["league"]["id"]
            for s in item["seasons"]:
                add(
                    "competition_seasons",
                    {
                        "competition_id": LEAGUES[league],
                        "season_id": f"{s['year']}-{s['year'] + 1}",
                        "expected_matches": competition(LEAGUES[league]).matches,
                        "coverage": json.dumps(s["coverage"], sort_keys=True),
                    },
                )
        elif endpoint == "teams":
            t = item["team"]
            add("teams", {"team_id": team_key(t, True), "api_id": t["id"], "name": t["name"]})
        elif endpoint == "standings":
            league = item["league"]
            if league["id"] not in LEAGUES:
                continue
            season = f"{league['season']}-{league['season'] + 1}"
            for table in league["standings"]:
                for row in table:
                    t = row["team"]
                    add(
                        "teams",
                        {"team_id": team_key(t, True), "api_id": t["id"], "name": t["name"]},
                    )
                    add(
                        "standings",
                        {
                            "competition_id": LEAGUES[league["id"]],
                            "season_id": season,
                            "team_id": team_key(t, True),
                            "rank": row["rank"],
                            "points": row["points"],
                            "played": row["all"]["played"],
                            "wins": row["all"]["win"],
                            "draws": row["all"]["draw"],
                            "losses": row["all"]["lose"],
                            "goals_for": row["all"]["goals"]["for"],
                            "goals_against": row["all"]["goals"]["against"],
                            "goal_difference": row["goalsDiff"],
                            "group_name": row.get("group"),
                            "description": row.get("description"),
                            "updated_at": row.get("update"),
                        },
                    )
        elif endpoint == "fixtures":
            league = item["league"]
            if league["id"] not in LEAGUES:
                continue
            season = f"{league['season']}-{league['season'] + 1}"
            comp = LEAGUES[league["id"]]
            stage = "regular" if league["round"].startswith("Regular Season") else "playoff"
            h, a = (team_key(item["teams"][s], True) for s in ("home", "away"))
            f = item["fixture"]
            key = (
                fixture_id(comp, season, h, a)
                if stage == "regular"
                else f"{comp}:{season}:playoff:{f['id']}"
            )
            status = f["status"]["short"]
            finished = status in ("FT", "AET", "PEN", "AWD", "WO")
            state = (
                "finished"
                if finished
                else "in_progress"
                if status in ("1H", "HT", "2H", "ET", "BT", "P", "INT", "SUSP", "LIVE")
                else "postponed"
                if status in ("PST", "CANC", "ABD")
                else "scheduled"
            )
            kickoff = f["date"]
            disputed = FIXTURE_DISPUTES.get(f["id"])
            if disputed is not None:
                if disputed["match_id"] != key:
                    raise ValueError(f"Reviewed fixture dispute names another match: {f['id']}")
                issues.append(
                    {
                        "table": "fixtures",
                        "match_id": key,
                        "api_id": f["id"],
                        "reported_values": {
                            "kickoff_time": kickoff,
                            "status": status,
                            "home_goals": item["goals"]["home"],
                            "away_goals": item["goals"]["away"],
                        },
                        "resolution": disputed["resolution"],
                    }
                )
                finished, state, kickoff = False, "disputed", None
            add(
                "fixtures",
                {
                    "match_id": key,
                    "competition_id": comp,
                    "season_id": season,
                    "stage": stage,
                    "home_team_id": h,
                    "away_team_id": a,
                    "api_id": f["id"],
                    "match_date": str(
                        datetime.fromisoformat(kickoff).astimezone(ZoneInfo("Europe/London")).date()
                    )
                    if kickoff
                    else None,
                    "kickoff_time": kickoff,
                    "status": state,
                    "home_goals": item["goals"]["home"] if finished else None,
                    "away_goals": item["goals"]["away"] if finished else None,
                },
            )
            base = {
                "match_id": key,
                "competition_id": comp,
                "season_id": season,
                "kickoff_time": kickoff,
            }
            for side in item.get("statistics") or []:
                team = team_key(side["team"], True)
                values = {}
                for entry in side.get("statistics") or []:
                    mapped = TEAM_STATISTICS.get(entry["type"])
                    if mapped:
                        values[mapped[0]] = team_statistic(entry["value"], mapped[1])
                if values:
                    add(
                        "team_statistics",
                        {
                            "match_id": key,
                            "team_id": team,
                            "competition_id": comp,
                            "season_id": season,
                            "api_id": f["id"],
                            **values,
                        },
                    )
            lineup, shirts = {}, {}
            for side in item.get("lineups", []):
                team = team_key(side["team"], True)
                for collection, starts in [("startXI", 1), ("substitutes", 0)]:
                    for p in side[collection]:
                        p = p["player"]
                        if not canonical_api_id(p["id"]):
                            continue
                        pid = player_id(p["id"])
                        if p.get("number") is not None:
                            key_number = team, p["number"]
                            identity = canonical_api_id(p["id"]), p["name"]
                            if key_number in shirts and shirts[key_number][0] != identity[0]:
                                raise ValueError("Conflicting same-team shirt numbers in lineup")
                            shirts[key_number] = identity
                        lineup[pid] = {
                            **base,
                            "team_id": team,
                            "player_id": pid,
                            "position": ROLES.get(p.get("pos"), "UNK"),
                            "starts": starts,
                        }
                        add(
                            "players",
                            {
                                "player_id": pid,
                                "api_id": canonical_api_id(p["id"]),
                                "name": p["name"],
                            },
                        )
            for side in item.get("players", []):
                team = team_key(side["team"], True)
                for entry in side["players"]:
                    p, s = entry["player"], entry["statistics"][0]
                    if not canonical_api_id(p["id"]):
                        known = shirts.get((team, s["games"].get("number")))
                        if known is None or not compatible_name(known[1], p["name"]):
                            continue
                        p = {**p, "id": known[0]}
                    pid = player_id(p["id"])
                    row = lineup.setdefault(
                        pid,
                        {
                            **base,
                            "team_id": team,
                            "player_id": pid,
                            "position": ROLES.get(s["games"]["position"], "UNK"),
                        },
                    )
                    if finished:
                        row.update(
                            {
                                "minutes": s["games"]["minutes"],
                                "goals": s["goals"]["total"],
                                "assists": s["goals"]["assists"],
                                "saves": s["goals"]["saves"],
                                "shots": s["shots"]["total"],
                                "shots_on_target": s["shots"]["on"],
                                "yellow_cards": s["cards"]["yellow"],
                                "red_cards": s["cards"]["red"],
                            }
                        )
                        row.update(
                            match_player_statistics(
                                s,
                                {"table": "appearances", "match_id": key, "player_id": pid},
                                issues,
                            )
                        )
                    add(
                        "players",
                        {"player_id": pid, "api_id": canonical_api_id(p["id"]), "name": p["name"]},
                    )
            for row in lineup.values():
                add("appearances", row)
        elif endpoint == "players":
            p = item["player"]
            pid = player_id(p["id"])
            add(
                "players",
                {
                    "player_id": pid,
                    "api_id": canonical_api_id(p["id"]),
                    "name": " ".join(filter(None, [p.get("firstname"), p.get("lastname")]))
                    or p["name"],
                    "birth_date": p.get("birth", {}).get("date"),
                },
            )
            for s in item["statistics"]:
                if (
                    s["league"]["id"] != context["league"]
                    or s["league"]["season"] != context["season"]
                ):
                    continue
                if not s["games"].get("appearences"):
                    continue
                add(
                    "memberships",
                    {
                        "player_id": pid,
                        "team_id": team_key(s["team"], True),
                        "season_id": f"{context['season']}-{context['season'] + 1}",
                        "competition_id": LEAGUES[context["league"]],
                        "position": ROLES.get(s["games"]["position"], "UNK"),
                        "basis": "retrospective_season_participation",
                        "scope": str(context["league"]),
                    },
                )
        elif endpoint == "players/squads":
            add(
                "teams",
                {
                    "team_id": team_key(item["team"], True),
                    "api_id": item["team"]["id"],
                    "name": item["team"]["name"],
                },
            )
            positions = {}
            for p in item["players"]:
                positions.setdefault(p["id"], set()).add(p["position"])
            for p in item["players"]:
                pid = player_id(p["id"])
                if pid is None:
                    issues.append(
                        {
                            "table": "memberships",
                            "team_id": team_key(item["team"], True),
                            "reported_values": {"id": p["id"], "name": p["name"]},
                            "resolution": "unknown: squad entry without a provider player id",
                        }
                    )
                    continue
                add(
                    "players",
                    {"player_id": pid, "api_id": canonical_api_id(p["id"]), "name": p["name"]},
                )
                add(
                    "memberships",
                    {
                        "player_id": pid,
                        "team_id": team_key(item["team"], True),
                        "season_id": record["context"]["season_id"],
                        "competition_id": record["context"]["competition_id"],
                        "position": ROLES.get(p["position"], "UNK")
                        if len(positions[p["id"]]) == 1
                        else "UNK",
                        "basis": "captured_squad",
                        "scope": str(item["team"]["id"]),
                    },
                )
        elif endpoint == "injuries":
            comp = LEAGUES[item["league"]["id"]]
            p, f = item["player"], item["fixture"]
            add(
                "availability",
                {
                    "player_id": player_id(p["id"]),
                    "team_id": team_key(item["team"], True),
                    "competition_id": comp,
                    "season_id": f"{item['league']['season']}-{item['league']['season'] + 1}",
                    "scope": f"fixture:{f['id']}",
                    "match_id": fixture_keys.get(f["id"]),
                    "status": {"Missing Fixture": "unavailable", "Questionable": "doubtful"}.get(
                        p["type"], "unknown"
                    ),
                    "reason": p["reason"],
                },
            )
        elif endpoint == "sidelined":
            add(
                "availability",
                {
                    "player_id": player_id(context["player"]),
                    "scope": "interval",
                    "status": "sidelined",
                    "reason": item["type"],
                    "start_date": item.get("start"),
                    "end_date": item.get("end") if item.get("end") not in ("Unknown", "") else None,
                },
            )
        elif endpoint == "transfers":
            p = item["player"]
            add(
                "players",
                {
                    "player_id": player_id(p["id"]),
                    "api_id": canonical_api_id(p["id"]),
                    "name": p.get("name"),
                },
            )
            for t in item["transfers"]:
                for team in t["teams"].values():
                    if team.get("id") is not None:
                        add(
                            "teams",
                            {
                                "team_id": team_key(team, known=team_keys),
                                "api_id": team["id"],
                                "name": team["name"],
                            },
                        )
                add(
                    "transfers",
                    {
                        "player_id": player_id(item["player"]["id"]),
                        "transfer_date": t["date"],
                        "from_team_id": team_key(t["teams"]["out"], known=team_keys),
                        "to_team_id": team_key(t["teams"]["in"], known=team_keys),
                        "transfer_type": t["type"],
                    },
                )
    for table, rows in tables.items():
        if table == "players":
            merged = {}
            for r in rows:
                merged.setdefault(r["player_id"], {}).update(r)
            tables[table] = list(merged.values())
        elif table == "teams":
            merged = {}
            for row in sorted(rows, key=lambda r: r["name"] or ""):
                key = row["team_id"]
                if key in merged and merged[key]["api_id"] != row["api_id"]:
                    raise ValueError(f"Conflicting provider team IDs: {key}")
                # Transfer histories contain spelling variants for the same provider ID.
                merged.setdefault(key, row)
            tables[table] = list(merged.values())
        elif table == "availability" and endpoint == "sidelined":
            episodes = {}
            for row in rows:
                key = row["player_id"], row["reason"], row["start_date"]
                episodes.setdefault(key, []).append(row)
            merged = []
            for key, entries in episodes.items():
                ends = {r["end_date"] for r in entries}
                row = dict(entries[0])
                if len(ends) > 1:
                    row["end_date"] = None
                    issues.append(
                        {
                            "table": "availability",
                            "player_id": key[0],
                            "reason": key[1],
                            "start_date": key[2],
                            "field": "end_date",
                            "reported_values": sorted(ends, key=lambda value: value or ""),
                            "resolution": "unknown: conflicting end dates in one provider response",
                        }
                    )
                merged.append(row)
            tables[table] = merged
        else:
            tables[table] = list({json.dumps(r, sort_keys=True): r for r in rows}.values())
    snapshots = source_snapshots(record, body, tables, root)
    if snapshots:
        tables["source_snapshots"] = snapshots
    if issues:
        record = {**record, "normalization_issues": issues}
    result = publish(root, record, tables)
    record_identity(root, tables)
    return result
