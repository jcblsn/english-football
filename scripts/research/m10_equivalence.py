"""Compare the production M10 with the selected research candidate in all four divisions.

The production path is `epl_forecast.cli.fitted_model` with `configs/product.toml`, fitted from the
start at each cutoff. The research path is the rolling run of `level-s0.08-form-s0.07` in
`m10_rolling.py`, which fitted day by day. The cutoffs are the first match days of three seasons
and a midseason day, so the matches include entrants and continuing clubs. The season simulation
is compared separately: a production panel of 2024/25 against the candidate panel.

Usage: uv run --with pandas --with pyarrow python scripts/research/m10_equivalence.py \
    --grid runs/m10-grid --panels runs/m10-panels --production-panels runs/m10-equivalence \
    --tables <directory>
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path.cwd() / "scripts"))

from evaluate_seasons import competition_config  # noqa: E402

from epl_forecast.cli import fitted_model  # noqa: E402
from epl_forecast.datasets import Dataset  # noqa: E402
from epl_forecast.storage import load_environment  # noqa: E402

DIVISIONS = ("eng-premier-league", "eng-championship", "eng-league-one", "eng-league-two")
CANDIDATE = "level-s0.08-form-s0.07"
PANEL_COLUMNS = ("mean_points", "points_sd", "points_crps", "rank_rps", "width_90")


def cutoffs(grid):
    days = []
    for season in ("2024-2025", "2025-2026", "2026-2027"):
        days.append(("first match day", grid[grid.season_id == season].match_date.min()))
    later = grid[(grid.season_id == "2025-2026") & (grid.match_date >= "2026-01-10")]
    days.append(("midseason", later.match_date.min()))
    return days


def match_rows(matches, grid_root):
    rows = []
    for division in DIVISIONS:
        grid = pd.read_parquet(grid_root / division / f"{CANDIDATE}.parquet")
        config, model_id = competition_config("M10", division)
        for label, day in cutoffs(grid):
            model, _, _ = fitted_model(matches, config, model_id, pd.Timestamp(day).date())
            expected = grid[grid.match_date == day].set_index("match_id")
            for match in matches:
                fixture = match.fixture
                if fixture.competition_id != division or str(fixture.match_date) != day:
                    continue
                forecast = model.predict_match(fixture)
                reference = expected.loc[fixture.match_id]
                home = model.team_summary(fixture.home_team_id, fixture.season_id)
                away = model.team_summary(fixture.away_team_id, fixture.season_id)
                rows.append(
                    {
                        "competition_id": division,
                        "cutoff": label,
                        "match_date": day,
                        "match_id": fixture.match_id,
                        "entrant_match": any(
                            state["state_source"] != "previous league state"
                            for state in (home, away)
                        ),
                        "probability_difference": float(
                            np.abs(
                                np.array(forecast.probabilities)
                                - reference[["p_home", "p_draw", "p_away"]].to_numpy(float)
                            ).max()
                        ),
                        "score_log_probability_difference": abs(
                            forecast.scores.log_probability(match.home_goals, match.away_goals)
                            - reference.score_log_probability
                        ),
                        "quality_difference": max(
                            abs(home["quality"] - reference.home_quality),
                            abs(away["quality"] - reference.away_quality),
                        ),
                    }
                )
        print(division, flush=True)
    return pd.DataFrame(rows)


def panel_rows(research_root, production_root):
    rows = []
    for division in DIVISIONS:
        production = pd.read_csv(production_root / f"panel-{division}" / "club_seasons.csv")
        research = pd.read_csv(research_root / f"c2-{division}" / "club_seasons.csv")
        keys = ["season_id", "origin", "team_id"]
        joined = production.merge(research, on=keys, suffixes=("_production", "_research"))
        if len(joined) != len(production):
            raise ValueError(f"The {division} panels do not have the same club-seasons")
        row = {"competition_id": division, "club_origins": len(joined)}
        for column in PANEL_COLUMNS:
            if f"{column}_production" in joined:
                row[f"{column}_max_difference"] = float(
                    (joined[f"{column}_production"] - joined[f"{column}_research"]).abs().max()
                )
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grid", type=Path, required=True)
    parser.add_argument("--panels", type=Path, required=True)
    parser.add_argument("--production-panels", type=Path, required=True)
    parser.add_argument("--tables", type=Path, required=True)
    args = parser.parse_args()
    load_environment()
    data = Dataset()
    try:
        matches = data.matches()
    finally:
        data.close()
    matches_table = match_rows(matches, args.grid)
    summary = (
        matches_table.groupby(["competition_id", "cutoff", "entrant_match"])
        .agg(
            matches=("match_id", "size"),
            probability=("probability_difference", "max"),
            score_log_probability=("score_log_probability_difference", "max"),
            quality=("quality_difference", "max"),
        )
        .reset_index()
    )
    panels = panel_rows(args.panels, args.production_panels)
    args.tables.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.tables / "equivalence_matches.csv", index=False)
    panels.to_csv(args.tables / "equivalence_panels.csv", index=False)
    pd.set_option("display.width", 200)
    print(summary.to_string())
    print(panels.to_string())


if __name__ == "__main__":
    main()
