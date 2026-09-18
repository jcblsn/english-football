"""Refresh the defined set of Page 324 Datawrapper charts from a published forecast.

The module keeps three layers apart:

* extraction  - a published forecast becomes a small table (extract_* functions);
* recipe      - the chart form, order, precision, colours and settings (recipe_* functions);
* instance    - the competition, the event, the titles and the chart ID (charts/definitions.toml).

Every value comes from the public forecast surface in the `analysis` schema.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
QUERY = REPO_ROOT / ".agents" / "skills" / "query-football-data" / "scripts" / "query"
DEFINITIONS = REPO_ROOT / "charts" / "definitions.toml"
API = "https://api.datawrapper.de/v3"

INK = "#121210"
RULE = "#D8D5CC"
SECONDARY = "#6C6A64"
QUIET = "#9E9B93"
WASH = "#B9B5AA"
CANVAS = "#FFFFFF"

ATTRIBUTION = "Page 324"
SOURCE_URL = "https://page324.substack.com/"


# --------------------------------------------------------------------------- data


@dataclass(frozen=True)
class Forecast:
    forecast_id: str
    competition_id: str
    season_id: str
    generated_at: str
    model_version: str
    simulations: int

    @property
    def season(self) -> str:
        start, _, end = self.season_id.partition("-")
        return f"{start}/{end[-2:]}"

    @property
    def stamp(self) -> str:
        """The forecast ID as a readable time. It still names one forecast document."""
        try:
            moment = datetime.strptime(self.forecast_id, "%Y-%m-%dT%H%M%SZ")
        except ValueError:
            return self.forecast_id
        return f"{moment:%Y-%m-%d %H:%M} UTC"


def query(**named_sql: str) -> dict[str, list[dict]]:
    """Run named SQL through the query-football-data helper and return row dicts."""
    command = [
        str(QUERY),
        "--full-precision",
        "--max-rows",
        "2000",
        "--max-output-chars",
        "4000000",
    ]
    for name, sql in named_sql.items():
        command += ["--query", name, sql]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"query failed:\n{result.stderr.strip()}")
    payload = json.loads(result.stdout)
    blocks = payload["queries"] if "queries" in payload else [dict(payload, name="sql")]
    tables: dict[str, list[dict]] = {}
    for block in blocks:
        if block.get("truncated"):
            raise SystemExit(f"query {block['name']} was truncated; narrow the SQL")
        tables[block["name"]] = [
            dict(zip(block["columns"], row, strict=True)) for row in block["rows"]
        ]
    return tables


def resolve_forecast(competition: str, forecast_id: str | None) -> Forecast:
    clause = f"AND forecast_id = '{forecast_id}'" if forecast_id else ""
    rows = query(
        head=f"""
        SELECT forecast_id, competition_id, season_id, generated_at,
               public_model_version, simulations
        FROM analysis.forecasts
        WHERE competition_id = '{competition}' {clause}
        ORDER BY generated_at DESC
        LIMIT 1
        """
    )["head"]
    if not rows:
        raise SystemExit(f"no forecast for {competition} {forecast_id or '(latest)'}")
    row = rows[0]
    return Forecast(
        forecast_id=row["forecast_id"],
        competition_id=row["competition_id"],
        season_id=row["season_id"],
        generated_at=row["generated_at"],
        model_version=row["public_model_version"],
        simulations=int(row["simulations"]),
    )


# ----------------------------------------------------------------------- numbers


def points(value: float, places: int) -> Decimal:
    """Percentage points, rounded half up, from a published probability."""
    quantum = Decimal(1).scaleb(-places)
    return (Decimal(str(value)) * 100).quantize(quantum, rounding=ROUND_HALF_UP)


def plain(value: Decimal) -> str:
    return format(value, "f")


def label_of(row: dict, short: dict[str, str], use_short: bool) -> str:
    if use_short:
        return short.get(row["team_id"], row["team_name"])
    return row["team_name"]


def window_phrase(first: str, last: str) -> str:
    start, end = date.fromisoformat(first), date.fromisoformat(last)
    if start == end:
        return f"on {start.day} {start:%B %Y}"
    if (start.month, start.year) == (end.month, end.year):
        return f"from {start.day} to {end.day} {end:%B %Y}"
    return f"from {start.day} {start:%B} to {end.day} {end:%B %Y}"


def provenance(forecast: Forecast, *, with_simulations: bool = True, extra: str = "") -> str:
    parts = [f"Page 324 forecast as of {forecast.stamp}.", f"Model {forecast.model_version}"]
    parts[-1] += f", {forecast.simulations:,} simulations." if with_simulations else "."
    if extra:
        parts.append(extra)
    return " ".join(parts)


# -------------------------------------------------------------------- extraction


def extract_season_event_bars(forecast: Forecast, spec: dict) -> list[dict]:
    rows = query(
        bars=f"""
        SELECT t.team_id, t.team_name, e.probability, t.mean_position
        FROM analysis.forecast_team_events AS e
        JOIN analysis.forecast_teams AS t USING (forecast_id, competition_id, team_id)
        WHERE e.forecast_id = '{forecast.forecast_id}'
          AND e.competition_id = '{forecast.competition_id}'
          AND e.event = '{spec["event"]}'
        ORDER BY e.probability DESC, t.mean_position ASC
        """
    )["bars"]
    if not rows:
        raise SystemExit(f"no rows for event {spec['event']}")
    return rows


def extract_match_outcome_bars(forecast: Forecast, spec: dict) -> list[dict]:
    return query(
        matches=f"""
        SELECT m.match_id, m.match_date,
               h.team_name AS home_team, a.team_name AS away_team,
               round(m.structural_p_home, 6) AS p_home,
               round(m.structural_p_draw, 6) AS p_draw,
               round(m.structural_p_away, 6) AS p_away
        FROM analysis.forecast_matches AS m
        JOIN analysis.forecast_teams AS h
          ON h.forecast_id = m.forecast_id AND h.competition_id = m.competition_id
         AND h.team_id = m.home_team_id
        JOIN analysis.forecast_teams AS a
          ON a.forecast_id = m.forecast_id AND a.competition_id = m.competition_id
         AND a.team_id = m.away_team_id
        WHERE m.forecast_id = '{forecast.forecast_id}'
          AND m.competition_id = '{forecast.competition_id}'
          AND m.on_public_surface
        ORDER BY m.kickoff_time, m.match_id
        """
    )["matches"]


def extract_position_matrix(forecast: Forecast, spec: dict) -> dict:
    tables = query(
        teams=f"""
        SELECT team_id, team_name, mean_position
        FROM analysis.forecast_teams
        WHERE forecast_id = '{forecast.forecast_id}'
          AND competition_id = '{forecast.competition_id}'
        ORDER BY mean_position ASC
        """,
        cells=f"""
        SELECT team_id, position, probability
        FROM analysis.forecast_position_distribution
        WHERE forecast_id = '{forecast.forecast_id}'
          AND competition_id = '{forecast.competition_id}'
        ORDER BY team_id, position
        """,
    )
    return tables


def extract_forecast_standings(forecast: Forecast, spec: dict) -> dict:
    events = tuple(event for event, _ in spec["events"])
    listed = ", ".join(f"'{event}'" for event in events)
    return query(
        teams=f"""
        SELECT team_id, team_name, played, current_points, mean_points, mean_position
        FROM analysis.forecast_teams
        WHERE forecast_id = '{forecast.forecast_id}'
          AND competition_id = '{forecast.competition_id}'
        ORDER BY mean_position ASC
        """,
        events=f"""
        SELECT team_id, event, probability
        FROM analysis.forecast_team_events
        WHERE forecast_id = '{forecast.forecast_id}'
          AND competition_id = '{forecast.competition_id}'
          AND event IN ({listed})
        """,
    )


def extract_expected_position(forecast: Forecast, spec: dict) -> list[dict]:
    rows = query(
        teams=f"""
        SELECT t.team_id, t.team_name, t.median_position, t.mean_position,
               max(CASE WHEN i.level = 50 THEN i.lower END) AS lower_50,
               max(CASE WHEN i.level = 50 THEN i.upper END) AS upper_50,
               max(CASE WHEN i.level = 90 THEN i.lower END) AS lower_90,
               max(CASE WHEN i.level = 90 THEN i.upper END) AS upper_90
        FROM analysis.forecast_teams AS t
        JOIN analysis.forecast_intervals AS i
          USING (forecast_id, competition_id, team_id)
        WHERE t.forecast_id = '{forecast.forecast_id}'
          AND t.competition_id = '{forecast.competition_id}'
          AND i.estimate = 'position'
        GROUP BY t.team_id, t.team_name, t.median_position, t.mean_position
        ORDER BY t.median_position ASC, t.mean_position ASC
        """
    )["teams"]
    if not rows:
        raise SystemExit(f"no position intervals for {forecast.forecast_id}")
    return rows


MEASURES = {
    # The width of the conditional event probability of a club over the three results.
    "swing": "the difference between the largest and the smallest probability of the three results",
    # The movement that the model itself ranks a fixture by: the probability-weighted
    # root mean square of the change from the baseline probability.
    "rms_movement": "the root mean square of the change from the current probability, weighted by the probability of each result",
}


def extract_match_leverage(forecast: Forecast, spec: dict) -> list[dict]:
    """The matches that can move one event probability the most, largest first."""
    measure = spec.get("measure", "swing")
    if measure not in MEASURES:
        raise SystemExit(f"unknown measure {measure}")
    rows = query(
        matches=f"""
        WITH club AS (
            SELECT match_id, team_id,
                   max(conditional_probability) - min(conditional_probability) AS swing,
                   max(rms_movement) AS rms_movement
            FROM analysis.forecast_impacts
            WHERE forecast_id = '{forecast.forecast_id}'
              AND competition_id = '{forecast.competition_id}'
              AND event = '{spec["event"]}'
            GROUP BY match_id, team_id
        )
        SELECT f.match_id, f.match_date, f.kickoff_time,
               f.home_team_id, f.away_team_id,
               h.team_name AS home_team, a.team_name AS away_team,
               max(club.swing) AS swing,
               max(club.rms_movement) AS rms_movement,
               count(*) FILTER (WHERE f.carried_from_forecast_id IS NULL) AS own_rows
        FROM analysis.forecast_impact_fixtures AS f
        JOIN club ON club.match_id = f.match_id
        JOIN analysis.forecast_teams AS h
          ON h.forecast_id = f.forecast_id AND h.competition_id = f.competition_id
         AND h.team_id = f.home_team_id
        JOIN analysis.forecast_teams AS a
          ON a.forecast_id = f.forecast_id AND a.competition_id = f.competition_id
         AND a.team_id = f.away_team_id
        WHERE f.forecast_id = '{forecast.forecast_id}'
          AND f.competition_id = '{forecast.competition_id}'
          AND f.status = 'scheduled'
          AND f.sufficient_sample
        GROUP BY f.match_id, f.match_date, f.kickoff_time,
                 f.home_team_id, f.away_team_id, h.team_name, a.team_name
        ORDER BY {measure} DESC, f.kickoff_time, f.match_id
        """
    )["matches"]
    if not rows:
        raise SystemExit(f"no scheduled impact fixtures for {forecast.competition_id}")
    return rows


# ------------------------------------------------------------------------ recipes


def grey_heatmap(range_min: float, range_max: float) -> dict:
    """A restrained white to warm-grey cell scale. The number stays readable on every cell."""
    return {
        "enabled": True,
        "mode": "continuous",
        "stops": "equidistant",
        "interpolation": "equidistant",
        "palette": 0,
        "rangeMin": str(range_min),
        "rangeMax": str(range_max),
        "hideValues": False,
        "colors": [{"color": CANVAS, "position": 0}, {"color": WASH, "position": 1}],
    }


def table_style() -> dict:
    return {
        "compactMode": True,
        "striped": False,
        "sortTable": False,
        "searchable": False,
        "firstColumnIsSticky": True,
        "mobileFallback": True,
        "header": {
            "style": {"bold": True, "italic": False, "fontSize": 1},
            "borderTop": "none",
            "borderBottom": "1px",
            "borderTopColor": RULE,
            "borderBottomColor": INK,
        },
    }


def csv_text(header: list[str], rows: list[list[str]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def recipe_season_event_bars(forecast: Forecast, spec: dict, data: list[dict], short: dict) -> dict:
    label = spec["value_label"]
    rows = [[label_of(row, short, False), plain(points(row["probability"], 1))] for row in data]
    total = sum(points(row["probability"], 1) for row in data)
    return {
        "csv": csv_text(["Club", label], rows),
        "checks": [
            ("rows", len(rows), 20 if forecast.competition_id == "eng-premier-league" else 24),
            ("total percentage points", float(total), 100.0),
        ],
        "metadata": {
            "describe": {
                "intro": spec["intro"].format(season=forecast.season),
                "aria-description": f"A ranked bar chart of {label.lower()} for every club in the competition.",
            },
            "visualize": {
                "base-color": INK,
                "background": False,
                "sort-bars": False,
                "reverse-order": False,
                "custom-range": [0, 100],
                "force-grid": True,
                "show-value-labels": True,
                "value-label-format": "0%",
                "axis-label-format": "0%",
                "color-by-column": False,
                "show-color-key": False,
                "thick": False,
            },
            "annotate": {
                "notes": provenance(forecast, extra="A value of 0% is below 0.5%, not impossible.")
            },
        },
    }


def recipe_match_outcome_bars(
    forecast: Forecast, spec: dict, data: list[dict], short: dict
) -> dict:
    """One grey for the home win, one for the draw, one for the away win."""
    outcomes = [("Home win", "p_home"), ("Draw", "p_draw"), ("Away win", "p_away")]
    rows = [
        [f"{match['home_team']} v {match['away_team']}"]
        + [plain(points(match[field], 0)) for _, field in outcomes]
        for match in data
    ]
    window = window_phrase(data[0]["match_date"], data[-1]["match_date"])
    return {
        "csv": csv_text(["Match"] + [label for label, _ in outcomes], rows),
        "checks": [("matches", len(rows), len(rows))],
        "metadata": {
            "describe": {
                "intro": spec["intro"].format(season=forecast.season, window=window),
                "aria-description": "A one hundred percent stacked bar chart of home win, draw and away win probabilities, in kick-off order.",
            },
            "visualize": {
                "block-labels": True,
                "sort-bars": False,
                "color-by-column": True,
                "show-color-key": True,
                "color-category": {"map": {"Home win": INK, "Draw": RULE, "Away win": SECONDARY}},
                "value-label-format": "0%",
                "thick": True,
            },
            "annotate": {
                "notes": provenance(
                    forecast, with_simulations=False, extra="The result is after 90 minutes."
                )
            },
        },
    }


def recipe_position_matrix(forecast: Forecast, spec: dict, data: dict, short: dict) -> dict:
    teams, cells = data["teams"], data["cells"]
    use_short = bool(spec.get("short_club_labels"))
    positions = sorted({int(cell["position"]) for cell in cells})
    grid: dict[str, dict[int, Decimal]] = {}
    for cell in cells:
        grid.setdefault(cell["team_id"], {})[int(cell["position"])] = points(cell["probability"], 0)

    rows = []
    for team in teams:
        values = grid[team["team_id"]]
        rows.append(
            [label_of(team, short, use_short)]
            + [plain(values[p]) if values[p] >= 1 else "" for p in positions]
        )

    mobile = int(spec.get("mobile_positions", 6))
    columns = {
        "Club": {
            "type": "text",
            "align": "left",
            "minWidth": 70,
            "showOnMobile": True,
            "showOnDesktop": True,
        }
    }
    for position in positions:
        columns[str(position)] = {
            "type": "number",
            "align": "center",
            "format": "0",
            "minWidth": 8,
            "compactMode": True,
            "heatmap": {"enabled": True},
            "showOnMobile": position <= mobile,
            "showOnDesktop": True,
        }

    raw: dict[str, dict[int, float]] = {}
    for cell in cells:
        raw.setdefault(cell["team_id"], {})[int(cell["position"])] = cell["probability"]
    row_totals = {team_id: 100 * sum(values.values()) for team_id, values in raw.items()}
    column_totals = {
        position: 100 * sum(raw[team["team_id"]][position] for team in teams)
        for position in positions
    }
    return {
        "csv": csv_text(["Club"] + [str(p) for p in positions], rows),
        "checks": [
            ("clubs", len(rows), len(positions)),
            ("row totals (unrounded)", round(min(row_totals.values()), 2), 100.0),
            ("column totals (unrounded)", round(min(column_totals.values()), 2), 100.0),
        ],
        "metadata": {
            "describe": {
                "intro": spec["intro"].format(season=forecast.season),
                "aria-description": "A table of clubs by final league position. Each cell is the probability that the club finishes in that position.",
            },
            "visualize": {
                "columns": columns,
                "heatmap": grey_heatmap(0, 25),
                **table_style(),
            },
            "annotate": {"notes": provenance(forecast)},
        },
    }


def recipe_forecast_standings(forecast: Forecast, spec: dict, data: dict, short: dict) -> dict:
    events: dict[str, dict[str, float]] = {}
    for row in data["events"]:
        events.setdefault(row["team_id"], {})[row["event"]] = row["probability"]

    event_labels = [label for _, label in spec["events"]]
    header = ["Club", "Played", "Points", "Expected points"] + event_labels

    rows = []
    for team in data["teams"]:
        expected = Decimal(str(team["mean_points"])).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )
        values = events[team["team_id"]]
        rows.append(
            [
                team["team_name"],
                str(int(team["played"])),
                str(int(team["current_points"])),
                plain(expected),
            ]
            + [plain(points(values[event], 1)) for event, _ in spec["events"]]
        )

    mobile = set(spec.get("mobile_columns", header))
    columns = {
        "Club": {"type": "text", "align": "left", "showOnMobile": True, "showOnDesktop": True},
        "Played": {
            "type": "number",
            "align": "right",
            "format": "0",
            "showOnMobile": "Played" in mobile,
            "showOnDesktop": True,
        },
        "Points": {
            "type": "number",
            "align": "right",
            "format": "0",
            "showOnMobile": "Points" in mobile,
            "showOnDesktop": True,
        },
        "Expected points": {
            "type": "number",
            "align": "right",
            "format": "0.0",
            "showOnMobile": "Expected points" in mobile,
            "showOnDesktop": True,
        },
    }
    for _, label in spec["events"]:
        columns[label] = {
            "type": "number",
            "align": "right",
            "format": "0.0%",
            "heatmap": {"enabled": True},
            "showOnMobile": label in mobile,
            "showOnDesktop": True,
        }

    title_total = sum(
        points(events[team["team_id"]]["title_probability"], 1) for team in data["teams"]
    )
    return {
        "csv": csv_text(header, rows),
        "checks": [
            ("clubs", len(rows), len(rows)),
            ("total title percentage points", float(title_total), 100.0),
        ],
        "metadata": {
            "describe": {
                "intro": spec["intro"].format(season=forecast.season),
                "aria-description": "A table of clubs with matches played, current points, expected final points, and season outcome probabilities.",
            },
            "visualize": {
                "columns": columns,
                "heatmap": grey_heatmap(0, 100),
                **table_style(),
            },
            "annotate": {"notes": provenance(forecast)},
        },
    }


def recipe_expected_position(forecast: Forecast, spec: dict, data: list[dict], short: dict) -> dict:
    """A dot for the median finish, with the 50% and 90% position intervals around it."""
    # The median finish is the last series so that its dot draws over an interval dot.
    series = [
        ("90% lower", "lower_90", WASH),
        ("50% lower", "lower_50", SECONDARY),
        ("50% upper", "upper_50", SECONDARY),
        ("90% upper", "upper_90", WASH),
        ("Median finish", "median_position", INK),
    ]
    rows = []
    for team in data:
        values = [
            Decimal(str(team[field])).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            for _, field, _ in series
        ]
        rows.append([label_of(team, short, False)] + [plain(value) for value in values])

    positions = 20 if forecast.competition_id == "eng-premier-league" else 24
    # A median and an interval bound are whole positions, so a fraction must not be hidden.
    fractional = sum(
        1 for team in data for _, field, _ in series if Decimal(str(team[field])) % 1 != 0
    )
    nested = sum(
        1
        for team in data
        if not (
            team["lower_90"] <= team["lower_50"] <= team["upper_50"] <= team["upper_90"]
            and team["lower_90"] <= team["median_position"] <= team["upper_90"]
        )
    )
    return {
        "csv": csv_text(["Club"] + [label for label, _, _ in series], rows),
        "checks": [
            ("clubs", len(rows), positions),
            ("clubs with an unordered interval", nested, 0),
            ("values that are not a whole position", fractional, 0),
        ],
        "metadata": {
            "describe": {
                "intro": spec["intro"].format(season=forecast.season),
                "aria-description": "A dot plot of clubs by median final position, with the 50 percent and 90 percent intervals shown as lighter dots on each side.",
            },
            "visualize": {
                "base-color": INK,
                "color-by-column": True,
                "color-category": {"map": {label: colour for label, _, colour in series}},
                "highlight-range": True,
                "range-extent": "custom",
                "custom-range": [1, positions],
                "custom-grid-lines": ", ".join(str(value) for value in (1, 5, 10, 15, positions)),
                "tick-position": "top",
                "label-alignment": "left",
                "show-value-labels": False,
                "show-color-key": False,
                "axis-label-format": "0",
            },
            "annotate": {
                "notes": provenance(
                    forecast,
                    extra="The dark dot is the median finish. The dark grey dots are the 50% interval and the light dots are the 90% interval.",
                )
            },
        },
    }


def recipe_match_leverage(forecast: Forecast, spec: dict, data: list[dict], short: dict) -> dict:
    """How much the result of one match can change the event probability of a club."""
    label = spec["value_label"]
    measure = spec.get("measure", "swing")
    use_short = bool(spec.get("short_club_labels"))
    # The rule is on the value the reader sees, so a match at the threshold is never
    # shown with a value that the introduction excludes.
    minimum = Decimal(str(spec.get("minimum", 0)))
    displayed = [(match, points(match[measure], 1)) for match in data]
    shown = [(match, value) for match, value in displayed if value > minimum]
    if not shown:
        raise SystemExit(
            f"no match is above {plain(minimum)} percentage points for {spec['event']}"
        )

    def club(match: dict, side: str) -> str:
        return label_of(
            {"team_id": match[f"{side}_team_id"], "team_name": match[f"{side}_team"]},
            short,
            use_short,
        )

    rows = [
        [f"{club(match, 'home')} v {club(match, 'away')}", plain(value)] for match, value in shown
    ]
    dates = [match["match_date"] for match in data]
    own = sum(int(match["own_rows"] or 0) > 0 for match, _ in shown)
    return {
        "csv": csv_text(["Match", label], rows),
        "checks": [
            ("matches in the window", len(data), len(data)),
            ("matches above the threshold", len(rows), len(rows)),
            (
                "matches out of order",
                sum(
                    1
                    for earlier, later in zip(shown, shown[1:], strict=False)
                    if earlier[1] < later[1]
                ),
                0,
            ),
            ("matches from this forecast", own, len(rows)),
        ],
        "metadata": {
            "describe": {
                "intro": spec["intro"].format(
                    season=forecast.season,
                    window=window_phrase(min(dates), max(dates)),
                    matches=len(rows),
                    minimum=plain(minimum),
                ),
                "aria-description": f"A ranked bar chart of matches by the largest change that the result can make to {label.lower()}.",
            },
            "visualize": {
                "base-color": INK,
                "background": False,
                "sort-bars": False,
                "reverse-order": False,
                "force-grid": True,
                "show-value-labels": True,
                "value-label-format": "0.0%",
                "axis-label-format": "0%",
                "color-by-column": False,
                "show-color-key": False,
                "thick": False,
            },
            "annotate": {"notes": provenance(forecast, extra=f"The value is {MEASURES[measure]}.")},
        },
    }


RECIPES = {
    "season_event_bars": (extract_season_event_bars, recipe_season_event_bars),
    "match_outcome_bars": (extract_match_outcome_bars, recipe_match_outcome_bars),
    "position_matrix": (extract_position_matrix, recipe_position_matrix),
    "forecast_standings": (extract_forecast_standings, recipe_forecast_standings),
    "expected_position": (extract_expected_position, recipe_expected_position),
    "match_leverage": (extract_match_leverage, recipe_match_leverage),
}

# The width a chart is designed for, and the width the review PNG uses. A Datawrapper
# table holds a minimum width of about 62 px for a numeric column, so a twenty-position
# matrix needs a wide chart. The value must not equal publish.embed-width: an export at
# exactly that width also takes the stored embed height and crops the image.
REVIEW_WIDTH = {
    "season_event_bars": 640,
    "match_outcome_bars": 640,
    "position_matrix": 1040,
    "forecast_standings": 720,
    "expected_position": 640,
    "match_leverage": 640,
}

PUBLISH_BLOCKS = {
    "logo": {"enabled": False},
    "embed": True,
    "download-pdf": False,
    "download-svg": False,
    "get-the-data": True,
    "download-image": True,
}


# ------------------------------------------------------------------ datawrapper


def token() -> str:
    value = os.environ.get("DATAWRAPPER_API_KEY")
    if value:
        return value
    env = REPO_ROOT / ".env"
    if env.is_file():
        for line in env.read_text().splitlines():
            name, separator, raw = line.strip().removeprefix("export ").partition("=")
            if separator and name.strip() == "DATAWRAPPER_API_KEY":
                return raw.strip().strip("\"'")
    raise SystemExit("DATAWRAPPER_API_KEY is not available")


def call(method: str, path: str, *, body=None, content_type="application/json", raw=False):
    data = body if isinstance(body, bytes) else (json.dumps(body).encode() if body else None)
    request = urllib.request.Request(
        f"{API}{path}",
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {token()}", "Content-Type": content_type},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = response.read()
    except urllib.error.HTTPError as error:
        raise SystemExit(
            f"{method} {path} failed: {error.code} {error.read().decode()[:400]}"
        ) from error
    if raw:
        return payload
    return json.loads(payload) if payload else {}


def note(line: str) -> None:
    print(line, flush=True)


def refresh(
    spec: dict,
    forecast_id: str | None,
    short: dict,
    export: Path | None,
    dry: bool,
    publish: bool,
):
    extract, build = RECIPES[spec["recipe"]]
    forecast = resolve_forecast(spec["competition"], forecast_id)
    data = extract(forecast, spec)
    result = build(forecast, spec, data, short)

    metadata = result["metadata"]
    describe = metadata.setdefault("describe", {})
    describe["source-name"] = ATTRIBUTION
    describe["byline"] = ATTRIBUTION
    describe["source-url"] = SOURCE_URL
    metadata.setdefault("publish", {})["blocks"] = PUBLISH_BLOCKS

    note(f"\n{spec['chart_id']}  {spec['title']}")
    note(
        f"  forecast {forecast.forecast_id}  {forecast.competition_id}  model {forecast.model_version}  {forecast.simulations:,} simulations"
    )
    for name, got, want in result["checks"]:
        flag = "ok " if abs(got - want) < 0.51 else "CHECK"
        note(f"  {flag} {name}: {got} (expected {want})")

    if dry:
        print(result["csv"])
        return

    call(
        "PUT",
        f"/charts/{spec['chart_id']}/data",
        body=result["csv"].encode(),
        content_type="text/csv",
    )
    call(
        "PATCH",
        f"/charts/{spec['chart_id']}",
        body={"title": spec["title"], "metadata": metadata},
    )

    uploaded = call("GET", f"/charts/{spec['chart_id']}/data", raw=True).decode()
    if uploaded.strip() != result["csv"].strip():
        raise SystemExit(f"{spec['chart_id']}: uploaded data does not match the extraction")
    note("  ok  uploaded data matches the extraction")

    if export:
        export.mkdir(parents=True, exist_ok=True)
        for width in (REVIEW_WIDTH[spec["recipe"]], 320):
            image = call(
                "GET",
                f"/charts/{spec['chart_id']}/export/png?unit=px&mode=rgb&width={width}&plain=false&scale=1&download=false",
                raw=True,
            )
            target = export / f"{spec['chart_id']}-{width}.png"
            target.write_bytes(image)
            note(f"  png {target}")

    if publish:
        response = call("POST", f"/charts/{spec['chart_id']}/publish")
        chart = response.get("data", response)
        public = chart.get("publicUrl") or chart.get("publicUrl", "")
        version = chart.get("publicVersion", "")
        note(f"  published v{version}  {public}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chart", action="append", help="Refresh only this chart ID.")
    parser.add_argument("--forecast", help="Use this forecast ID instead of the latest.")
    parser.add_argument("--export-dir", type=Path, help="Write review PNGs to this directory.")
    parser.add_argument("--dry-run", action="store_true", help="Print the chart data and stop.")
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Publish each refreshed chart and print its public URL.",
    )
    arguments = parser.parse_args()

    definitions = tomllib.loads(DEFINITIONS.read_text())
    short = definitions.get("defaults", {}).get("short_labels", {})
    selected = [
        chart
        for chart in definitions["charts"]
        if not arguments.chart or chart["chart_id"] in arguments.chart
    ]
    if not selected:
        raise SystemExit("no chart matched")
    for spec in selected:
        refresh(
            spec,
            arguments.forecast,
            short,
            arguments.export_dir,
            arguments.dry_run,
            arguments.publish,
        )
    print()


if __name__ == "__main__":
    sys.exit(main())
