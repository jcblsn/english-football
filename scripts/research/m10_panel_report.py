"""Compare the M7 control season panels with the M10 candidate panels.

Each division has two panel outputs from `evaluate_seasons.py`: `control-<division>` with M7 and
`c2-<division>` with the candidate. They use the same seasons, origins, seed and paths.

Usage: uv run --with pandas python scripts/research/m10_panel_report.py --panels runs/m10-panels
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TABLES = ROOT / "docs/experiments/m10_quality_dynamics/tables"
DIVISIONS = ("eng-premier-league", "eng-championship", "eng-league-one", "eng-league-two")
ORIGINS = ("preseason", "MW6", "MW12", "MW19", "MW30")
KEYS = ["season_id", "origin", "team_id"]
SCORES = ("rank_rps", "points_crps")
EVENTS = (
    "title",
    "top_four",
    "top_five",
    "relegation",
    "promotion",
    "automatic_promotion",
    "playoff_qualification",
)


def season_interval(diff, seasons, draws=10000, seed=20260917):
    frame = (
        pd.DataFrame({"diff": diff, "season": seasons})
        .groupby("season")["diff"]
        .agg(["sum", "count"])
    )
    rng = np.random.default_rng(seed)
    picks = rng.integers(len(frame), size=(draws, len(frame)))
    means = frame["sum"].to_numpy()[picks].sum(axis=1) / frame["count"].to_numpy()[picks].sum(
        axis=1
    )
    return np.quantile(means, [0.025, 0.975])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panels", type=Path, default=ROOT / "runs/m10-panels")
    args = parser.parse_args()
    rows, seasons_rows, cohort_rows = [], [], []
    for division in DIVISIONS:
        if not (args.panels / f"control-{division}" / "summary.csv").exists():
            print(f"No finished control panel for {division}")
            continue
        control = pd.read_csv(args.panels / f"control-{division}" / "club_seasons.csv")
        candidate = pd.read_csv(args.panels / f"c2-{division}" / "club_seasons.csv")
        joined = control.merge(candidate, on=KEYS, suffixes=("_m7", "_m10"))
        if len(joined) != len(control) or len(joined) != len(candidate):
            raise ValueError(f"The panels of {division} do not match")
        for origin in ORIGINS:
            j = joined[joined.origin == origin]
            row = {
                "competition_id": division,
                "origin": origin,
                "club_seasons": len(j),
                "seasons": j.season_id.nunique(),
            }
            for score in SCORES:
                diff = (j[f"{score}_m10"] - j[f"{score}_m7"]).to_numpy()
                low, high = season_interval(diff, j.season_id.to_numpy())
                row.update(
                    {
                        f"{score}_m7": j[f"{score}_m7"].mean(),
                        f"{score}_m10": j[f"{score}_m10"].mean(),
                        f"{score}_difference": diff.mean(),
                        f"{score}_low": low,
                        f"{score}_high": high,
                    }
                )
            for level in (50, 80, 90):
                for prefix in ("coverage", "width", "rank_coverage"):
                    for model in ("m7", "m10"):
                        row[f"{prefix}_{level}_{model}"] = j[f"{prefix}_{level}_{model}"].mean()
            for event in EVENTS:
                if f"{event}_brier_m7" in j and j[f"{event}_brier_m7"].notna().all():
                    diff = (j[f"{event}_brier_m10"] - j[f"{event}_brier_m7"]).to_numpy()
                    low, high = season_interval(diff, j.season_id.to_numpy())
                    row.update(
                        {
                            f"{event}_brier_difference": diff.mean(),
                            f"{event}_brier_low": low,
                            f"{event}_brier_high": high,
                        }
                    )
            rows.append(row)
            for season, g in j.groupby("season_id"):
                seasons_rows.append(
                    {
                        "competition_id": division,
                        "origin": origin,
                        "season_id": season,
                        **{
                            f"{s}_difference": (g[f"{s}_m10"] - g[f"{s}_m7"]).mean() for s in SCORES
                        },
                    }
                )
            for cohort, g in j.groupby("entry_cohort_m7"):
                cohort_rows.append(
                    {
                        "competition_id": division,
                        "origin": origin,
                        "entry_cohort": cohort,
                        "club_seasons": len(g),
                        "points_bias_m7": g.points_error_m7.mean(),
                        "points_bias_m10": g.points_error_m10.mean(),
                        **{
                            f"{s}_difference": (g[f"{s}_m10"] - g[f"{s}_m7"]).mean() for s in SCORES
                        },
                    }
                )
    TABLES.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(TABLES / "panel_comparison.csv", index=False)
    pd.DataFrame(seasons_rows).to_csv(TABLES / "panel_seasons.csv", index=False)
    pd.DataFrame(cohort_rows).to_csv(TABLES / "panel_cohorts.csv", index=False)


if __name__ == "__main__":
    main()
