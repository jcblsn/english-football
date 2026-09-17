"""Compare the season panels of one pre-merge candidate with the M10 candidate panels.

Both panels use the same seasons, origins, seed and paths. The M10 panels are `c2-<division>` of the
M10 memo; the candidate panels are `<candidate>-<division>` of `m10_premerge_panel.py`.

Usage: uv run --with pandas python scripts/research/m10_premerge_panel_report.py \
    --control runs/m10-panels --panels runs/m10-premerge-panels --candidate E1 --tables <directory>
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

DIVISIONS = ("eng-premier-league", "eng-championship", "eng-league-one", "eng-league-two")
ORIGINS = ("preseason", "MW6", "MW12", "MW19", "MW30")
KEYS = ["season_id", "origin", "team_id"]
SCORES = ("rank_rps", "points_crps")


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
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--panels", type=Path, required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--tables", type=Path, required=True)
    args = parser.parse_args()
    name = args.candidate.lower()
    rows, cohorts = [], []
    for division in DIVISIONS:
        control = pd.read_csv(args.control / f"c2-{division}" / "club_seasons.csv")
        candidate = pd.read_csv(args.panels / f"{args.candidate}-{division}" / "club_seasons.csv")
        joined = control.merge(candidate, on=KEYS, suffixes=("_m10", f"_{name}"))
        if len(joined) != len(control) or len(joined) != len(candidate):
            raise ValueError(f"The panels of {division} do not match")
        for origin in ORIGINS:
            j = joined[joined.origin == origin]
            row = {"competition_id": division, "origin": origin, "club_seasons": len(j)}
            for score in SCORES:
                diff = (j[f"{score}_{name}"] - j[f"{score}_m10"]).to_numpy()
                low, high = season_interval(diff, j.season_id.to_numpy())
                row.update(
                    {
                        f"{score}_m10": j[f"{score}_m10"].mean(),
                        f"{score}_difference": diff.mean(),
                        f"{score}_low": low,
                        f"{score}_high": high,
                    }
                )
            for model in ("m10", name):
                row[f"coverage_90_{model}"] = j[f"coverage_90_{model}"].mean()
                row[f"width_90_{model}"] = j[f"width_90_{model}"].mean()
            rows.append(row)
            for cohort, g in j.groupby("entry_cohort_m10"):
                cohorts.append(
                    {
                        "competition_id": division,
                        "origin": origin,
                        "entry_cohort": cohort,
                        "club_seasons": len(g),
                        "points_bias_m10": g.points_error_m10.mean(),
                        f"points_bias_{name}": g[f"points_error_{name}"].mean(),
                        "coverage_90_m10": g.coverage_90_m10.mean(),
                        f"coverage_90_{name}": g[f"coverage_90_{name}"].mean(),
                        "width_90_m10": g.width_90_m10.mean(),
                        f"width_90_{name}": g[f"width_90_{name}"].mean(),
                        **{
                            f"{s}_difference": (g[f"{s}_{name}"] - g[f"{s}_m10"]).mean()
                            for s in SCORES
                        },
                    }
                )
    args.tables.mkdir(parents=True, exist_ok=True)
    comparison, cohort_table = pd.DataFrame(rows), pd.DataFrame(cohorts)
    comparison.to_csv(args.tables / f"panel_{name}.csv", index=False, float_format="%.5f")
    cohort_table.to_csv(args.tables / f"panel_{name}_cohorts.csv", index=False, float_format="%.4f")
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print(comparison.round(4).to_string())
    print(cohort_table[cohort_table.origin == "preseason"].round(3).to_string())


if __name__ == "__main__":
    main()
