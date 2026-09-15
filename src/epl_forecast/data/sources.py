import csv
import io

from epl_forecast.competitions import (
    ENTRY_SOURCE_COMPETITIONS as ENTRY_SOURCE_DIVISIONS,
)
from epl_forecast.competitions import FORECAST_COMPETITIONS as FORECAST_DIVISIONS

FORECAST_COMPETITIONS = {
    c.football_data_division: {"id": c.competition_id, "teams": c.teams, "matches": c.matches}
    for c in FORECAST_DIVISIONS
}
ENTRY_SOURCE_COMPETITIONS = {
    c.football_data_division: {"id": c.competition_id, "teams": c.teams, "matches": c.matches}
    for c in ENTRY_SOURCE_DIVISIONS
}
COMPETITIONS = FORECAST_COMPETITIONS
REQUIRED_FIELDS = {"Div", "Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"}


def csv_rows(payload: bytes) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    fields = reader.fieldnames or []
    if not REQUIRED_FIELDS.issubset(fields):
        raise ValueError(f"Missing CSV fields: {sorted(REQUIRED_FIELDS - set(fields))}")
    rows = []
    for line, row in enumerate(reader, 2):
        if not any(value for value in row.values()):
            continue
        extra = row.pop(None, None)
        if extra and any(extra):
            raise ValueError(f"Unexpected extra CSV values at row {line}")
        rows.append((line, {key: (value or "").strip() for key, value in row.items()}))
    if not rows:
        raise ValueError("Source CSV contains no matches")
    return fields, rows


def season_name(start: int) -> str:
    if not 1993 <= start <= 2098:
        raise ValueError("Season start must be between 1993 and 2098")
    return f"{start}-{start + 1}"


def source_url(start: int, division: str) -> str:
    season_name(start)
    if division not in ENTRY_SOURCE_COMPETITIONS:
        raise ValueError(f"Unsupported division: {division}")
    code = f"{start % 100:02d}{(start + 1) % 100:02d}"
    return f"https://football-data.co.uk/mmz4281/{code}/{division}.csv"
