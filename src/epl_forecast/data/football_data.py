import csv
import io
import math
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from epl_forecast.data.sources import COMPETITIONS, ENTRY_SOURCE_COMPETITIONS, csv_rows
from epl_forecast.schema import Fixture, Match, fixture_id

TEAM_FILE = Path(__file__).with_name("teams.csv")
ODDS_FAMILIES = {
    "bet365_preclosing": ("B365H", "B365D", "B365A"),
    "betbrain_average_preclosing": ("BbAvH", "BbAvD", "BbAvA"),
    "market_average_preclosing": ("AvgH", "AvgD", "AvgA"),
    "market_average_closing": ("AvgCH", "AvgCD", "AvgCA"),
}
ODDS_FIELDS = [
    "match_id",
    "family",
    "home_odds",
    "draw_odds",
    "away_odds",
    "source_columns",
    "source_sha256",
    "source_row",
    "observed_at",
]


def team_aliases(path: Path = TEAM_FILE) -> dict[str, str]:
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    aliases = {row["source_name"]: row["team_id"] for row in rows}
    if len(aliases) != len(rows) or any(not value for value in aliases.values()):
        raise ValueError("Invalid team alias registry")
    return aliases


def parse_date(value: str) -> date:
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Invalid source date: {value!r}")


def parse_score(value: str) -> int:
    if not value.isascii() or not value.isdecimal():
        raise ValueError(f"Invalid goal count: {value!r}")
    return int(value)


def normalize_rows(
    payload: bytes, entry: dict, aliases: dict[str, str]
) -> tuple[list[Match], list[dict], dict]:
    fields, rows = csv_rows(payload)
    matches, odds = [], []
    quote_status = {family: Counter() for family in ODDS_FAMILIES}
    for row_number, row in rows:
        try:
            if row["Div"] != entry["division"]:
                raise ValueError("Division does not match the source manifest")
            for key in ("HomeTeam", "AwayTeam"):
                if row[key] not in aliases:
                    raise ValueError(f"Unknown team alias: {row[key]!r}; update teams.csv")
            home, away = aliases[row["HomeTeam"]], aliases[row["AwayTeam"]]
            played_on = parse_date(row["Date"])
            year = entry["season_start"]
            if not date(year, 7, 1) <= played_on < date(year + 1, 8, 1):
                raise ValueError("Match date falls outside its season")
            fixture = Fixture(
                fixture_id(entry["competition_id"], entry["season_id"], home, away),
                entry["competition_id"],
                entry["season_id"],
                played_on,
                home,
                away,
            )
            match = Match(
                fixture,
                parse_score(row["FTHG"]),
                parse_score(row["FTAG"]),
                entry["sha256"],
                row_number,
                row.get("Time", ""),
            )
            if match.outcome != row["FTR"]:
                raise ValueError("Full-time result disagrees with goals")
            matches.append(match)
            for family, columns in ODDS_FAMILIES.items():
                if any(not row.get(column) for column in columns):
                    quote_status[family]["missing"] += 1
                    continue
                try:
                    values = [float(row[column]) for column in columns]
                    valid = all(math.isfinite(value) and value > 1 for value in values)
                except ValueError:
                    valid = False
                if not valid:
                    quote_status[family]["invalid"] += 1
                    continue
                quote_status[family]["valid"] += 1
                odds.append(
                    dict(
                        zip(
                            ODDS_FIELDS,
                            [
                                fixture.match_id,
                                family,
                                *values,
                                ";".join(columns),
                                entry["sha256"],
                                row_number,
                                "",
                            ],
                            strict=True,
                        )
                    )
                )
        except ValueError as error:
            raise ValueError(
                f"{entry['season_id']} {entry['division']} row {row_number}: {error}"
            ) from error

    validate_unique(matches)
    teams = {team for m in matches for team in (m.fixture.home_team_id, m.fixture.away_team_id)}
    expected_teams = ENTRY_SOURCE_COMPETITIONS[entry["division"]]["teams"]
    if entry["division"] == "E0" and entry["season_start"] < 1995:
        expected_teams = 22
    n = len(matches)
    home_mean = sum(m.home_goals for m in matches) / n
    away_mean = sum(m.away_goals for m in matches) / n
    audit = {
        "season_id": entry["season_id"],
        "division": entry["division"],
        "matches": n,
        "teams": len(teams),
        "expected_teams": expected_teams,
        "expected_matches": expected_teams * (expected_teams - 1),
        "complete": len(teams) == expected_teams and n == expected_teams * (expected_teams - 1),
        "date_min": min(m.fixture.match_date for m in matches).isoformat(),
        "date_max": max(m.fixture.match_date for m in matches).isoformat(),
        "source_sha256": entry["sha256"],
        "columns": [f for f in fields if f],
        "missing_by_column": {f: sum(not row.get(f) for _, row in rows) for f in fields if f},
        "odds": {family: dict(counts) for family, counts in quote_status.items()},
        "outcomes": dict(Counter(m.outcome for m in matches)),
        "mean_home_goals": home_mean,
        "mean_away_goals": away_mean,
        "variance_home_goals": sum((m.home_goals - home_mean) ** 2 for m in matches) / n,
        "variance_away_goals": sum((m.away_goals - away_mean) ** 2 for m in matches) / n,
        "goal_covariance": sum(
            (m.home_goals - home_mean) * (m.away_goals - away_mean) for m in matches
        )
        / n,
        "score_0_0": sum(m.home_goals == m.away_goals == 0 for m in matches),
    }
    return matches, odds, audit


def validate_unique(matches: list[Match]) -> None:
    counts = Counter(m.fixture.match_id for m in matches)
    duplicates = [key for key, count in counts.items() if count > 1]
    if duplicates:
        raise ValueError(f"Duplicate fixture IDs: {duplicates[:3]}")


def match_record(match: Match) -> dict:
    return {
        **asdict(match.fixture),
        "match_date": match.fixture.match_date.isoformat(),
        "home_goals": match.home_goals,
        "away_goals": match.away_goals,
        "outcome": match.outcome,
        "available_on": match.available_on.isoformat(),
        "source_sha256": match.source_sha256,
        "source_row": match.source_row,
        "source_time": match.source_time,
    }


def ingest(root, record, payload):
    from epl_forecast.datasets import publish

    context = record["context"]
    if context.get("kind") == "latest_odds":
        return ingest_latest_odds(root, record, payload)
    entry = {**context, "sha256": record["source_sha256"]}
    matches, odds, audit = normalize_rows(payload, entry, team_aliases())
    fixtures = [{**match_record(m), "stage": "regular", "status": "finished"} for m in matches]
    for r in fixtures:
        r.pop("outcome")
        r.pop("available_on")
        r.pop("source_sha256")
    raw = dict(csv_rows(payload)[1])
    process, issues = [], []
    for m in matches:
        row = raw[m.source_row]
        for t, prefix in [(m.fixture.home_team_id, "H"), (m.fixture.away_team_id, "A")]:
            shots, target = row.get(prefix + "S"), row.get(prefix + "ST")
            if (
                shots
                and target
                and shots.isdigit()
                and target.isdigit()
                and int(target) > int(shots)
            ):
                issues.append(
                    {
                        "match_id": m.fixture.match_id,
                        "team_id": t,
                        "reason": "shots_on_target exceeds shots; both unknown",
                        "shots": shots,
                        "shots_on_target": target,
                    }
                )
                shots, target = None, None
            process.append(
                {
                    "match_id": m.fixture.match_id,
                    "team_id": t,
                    "competition_id": m.fixture.competition_id,
                    "season_id": m.fixture.season_id,
                    "shots": int(shots) if shots and shots.isdigit() else None,
                    "shots_on_target": int(target) if target and target.isdigit() else None,
                }
            )
    quotes = [
        {
            k: v or None
            for k, v in q.items()
            if k not in ("source_columns", "source_row", "source_sha256")
        }
        for q in odds
    ]
    for q in quotes:
        q.update({"competition_id": entry["competition_id"], "season_id": entry["season_id"]})
    teams = sorted({t for m in matches for t in (m.fixture.home_team_id, m.fixture.away_team_id)})
    return publish(
        root,
        {**record, "normalization_issues": issues} if issues else record,
        {
            "fixtures": fixtures,
            "odds": quotes,
            "team_process": process,
            "competition_seasons": [
                {
                    "competition_id": entry["competition_id"],
                    "season_id": entry["season_id"],
                    "team_ids": teams,
                    "expected_matches": audit["expected_matches"],
                }
            ],
        },
    )


def ingest_latest_odds(root, record, payload):
    from epl_forecast.datasets import Dataset, publish

    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    if not {"Div", "Date", "HomeTeam", "AwayTeam"}.issubset(reader.fieldnames or []):
        raise ValueError("Latest odds response lacks fixture identity columns")
    aliases = team_aliases()
    data = Dataset(root, record["retrieved_at"])
    fixtures = {f["match_id"]: f for f in data.fixtures()}
    data.close()
    scheduled = {(f["competition_id"], f["season_id"]) for f in fixtures.values()}
    rows, unscheduled = [], {}
    for row in reader:
        if row["Div"] not in COMPETITIONS:
            continue
        for side in ("HomeTeam", "AwayTeam"):
            if row[side] not in aliases:
                raise ValueError(f"Unknown team alias: {row[side]!r}; update teams.csv")
        comp = COMPETITIONS[row["Div"]]["id"]
        season = record["context"]["season_id"]
        if (comp, season) not in scheduled:
            # Quotes captured before this archive held the competition's schedule stay unlinked.
            unscheduled[comp] = unscheduled.get(comp, 0) + 1
            continue
        key = fixture_id(comp, season, aliases[row["HomeTeam"]], aliases[row["AwayTeam"]])
        fixture = fixtures.get(key)
        if fixture is None or fixture["match_date"] != parse_date(row["Date"]):
            raise ValueError(f"Latest odds fixture does not match canonical schedule: {key}")
        for family, columns in ODDS_FAMILIES.items():
            if any(not row.get(c) for c in columns):
                continue
            values = [float(row[c]) for c in columns]
            if not all(math.isfinite(v) and v > 1 for v in values):
                raise ValueError(f"Invalid latest odds: {key}")
            rows.append(
                {
                    "match_id": key,
                    "competition_id": comp,
                    "season_id": season,
                    "family": family,
                    "home_odds": values[0],
                    "draw_odds": values[1],
                    "away_odds": values[2],
                    "observed_at": record["retrieved_at"],
                }
            )
    if unscheduled:
        record = {
            **record,
            "normalization_issues": [
                {
                    "table": "odds",
                    "competition_id": comp,
                    "season_id": record["context"]["season_id"],
                    "rows": count,
                    "resolution": "unknown: no captured schedule for this competition at retrieval",
                }
                for comp, count in sorted(unscheduled.items())
            ],
        }
    return publish(root, record, {"odds": rows})
