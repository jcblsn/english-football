"""Score the frozen matchday-squad adjustment on rolling M10 and M7 forecasts.

The shifts come from the history-only hindcast of the personnel research
(`research/evidence/personnel-measurement/68cba95/pm-hindcast-report/chronological.csv`): the
earlier-season κ times the estimated D_away − D_home, and the oracle shift from the realized squads.
The frozen arm uses the released κ. The structural forecasts come from `m10_premerge_rolling.py`.
No coefficient is fitted here.

Usage: uv run --with pandas --with pyarrow python scripts/research/m10_personnel.py \
    --evidence <chronological.csv> --rolling runs/m10-premerge --tables <directory>
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from epl_forecast.models.poisson import PoissonMixture
from epl_forecast.models.quality_tilt_scores import ScoreMixture
from epl_forecast.personnel import KAPPA

COMPETITIONS = ("eng-premier-league", "eng-championship")
CANDIDATES = ("M7", "M10")
ARMS = ("control", "hindcast", "frozen", "oracle")
METRICS = ("hda_log_loss", "brier", "score_nll")
OUTCOMES = {"H": 0, "D": 1, "A": 2}
SEED = 20260917


def scores(row, shift):
    components, weights = [], []
    index = 0
    while f"m{index}_weight" in row:
        mean = np.array([row[f"m{index}_home_mean"] + shift, row[f"m{index}_away_mean"] - shift])
        covariance = np.array(
            [
                [row[f"m{index}_home_variance"], row[f"m{index}_covariance"]],
                [row[f"m{index}_covariance"], row[f"m{index}_away_variance"]],
            ]
        )
        components.append(PoissonMixture(mean, covariance, 9))
        weights.append(row[f"m{index}_weight"])
        index += 1
    return ScoreMixture(components, weights)


def metrics(distribution, row):
    p = np.asarray(distribution.outcome_probabilities())
    observed = np.zeros(3)
    observed[OUTCOMES[row["outcome"]]] = 1
    return {
        "hda_log_loss": float(-np.log(p[OUTCOMES[row["outcome"]]])),
        "brier": float(((p - observed) ** 2).sum()),
        "score_nll": float(-distribution.log_probability(row["home_goals"], row["away_goals"])),
    }


def cluster_interval(frame, column, draws=2000):
    clusters = frame.groupby(["competition_id", "season_id"])[column].agg(["sum", "count"])
    rng = np.random.default_rng(SEED)
    picks = rng.integers(len(clusters), size=(draws, len(clusters)))
    means = clusters["sum"].to_numpy()[picks].sum(axis=1) / clusters["count"].to_numpy()[
        picks
    ].sum(axis=1)
    effects = clusters["sum"] / clusters["count"]
    return (*np.quantile(means, [0.025, 0.975]), int((effects < 0).sum()), len(clusters))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--rolling", type=Path, required=True)
    parser.add_argument("--tables", type=Path, required=True)
    args = parser.parse_args()
    evidence = pd.read_csv(args.evidence)
    rows = []
    for candidate in CANDIDATES:
        forecasts = pd.concat(
            pd.read_parquet(args.rolling / competition / f"{candidate}.parquet")
            for competition in COMPETITIONS
        )
        joined = evidence.merge(forecasts, on=["match_id", "competition_id", "season_id"])
        if len(joined) != len(evidence):
            raise ValueError(f"{candidate} has {len(joined)} of {len(evidence)} hindcast matches")
        for record in joined.to_dict("records"):
            shifts = {
                "control": 0.0,
                "hindcast": record["hindcast_delta"],
                "frozen": KAPPA * record["estimated_difference"],
                "oracle": record["oracle_delta"],
            }
            result = {
                "candidate": candidate,
                "match_id": record["match_id"],
                "competition_id": record["competition_id"],
                "season_id": record["season_id"],
                "opening_five": record["opening_five"],
                "realized_difference": record["realized_difference"],
                "archived_m7_control_score_nll": record["control_score_nll"],
                "home_club_match": record["home_season_matches"] + 1,
                "away_club_match": record["away_season_matches"] + 1,
            }
            for arm, shift in shifts.items():
                for metric, value in metrics(scores(record, shift), record).items():
                    result[f"{arm}_{metric}"] = value
            rows.append(result)
    scored = pd.DataFrame(rows)
    for arm in ARMS[1:]:
        for metric in METRICS:
            scored[f"{arm}_minus_control_{metric}"] = (
                scored[f"{arm}_{metric}"] - scored[f"control_{metric}"]
            )
    scopes = {
        "All": lambda f: f.index == f.index,
        "Premier League": lambda f: f.competition_id == "eng-premier-league",
        "Championship": lambda f: f.competition_id == "eng-championship",
        "Opening five matches": lambda f: f.opening_five,
        "After the opening five": lambda f: ~f.opening_five,
        "2025/26": lambda f: f.season_id == "2025-2026",
        "Realized absolute D difference at least 0.20": lambda f: f.realized_difference.abs() >= 0.2,
    }
    summary = []
    for candidate in CANDIDATES:
        frame = scored[scored.candidate == candidate]
        for scope, select in scopes.items():
            part = frame[select(frame)]
            row = {"candidate": candidate, "scope": scope, "matches": len(part)}
            for arm in ARMS[1:]:
                for metric in METRICS:
                    row[f"{arm}_minus_control_{metric}"] = part[
                        f"{arm}_minus_control_{metric}"
                    ].mean()
            summary.append(row)
    summary = pd.DataFrame(summary)
    intervals = []
    for candidate in CANDIDATES:
        frame = scored[scored.candidate == candidate]
        for arm in ARMS[1:]:
            for metric in METRICS:
                low, high, below, clusters = cluster_interval(
                    frame, f"{arm}_minus_control_{metric}"
                )
                intervals.append(
                    {
                        "candidate": candidate,
                        "comparison": f"{arm} minus control",
                        "metric": metric,
                        "mean": frame[f"{arm}_minus_control_{metric}"].mean(),
                        "low": low,
                        "high": high,
                        "clusters_below_zero": below,
                        "clusters": clusters,
                    }
                )
    wide = scored.pivot_table(
        index=["match_id", "competition_id", "season_id"],
        columns="candidate",
        values=[f"hindcast_minus_control_{m}" for m in METRICS],
    )
    interaction = pd.DataFrame(
        {m: wide[(f"hindcast_minus_control_{m}", "M10")] - wide[(f"hindcast_minus_control_{m}", "M7")] for m in METRICS}
    ).reset_index()
    for metric in METRICS:
        low, high, below, clusters = cluster_interval(interaction, metric)
        intervals.append(
            {
                "candidate": "M10 minus M7",
                "comparison": "hindcast gain on M10 minus hindcast gain on M7",
                "metric": metric,
                "mean": interaction[metric].mean(),
                "low": low,
                "high": high,
                "clusters_below_zero": below,
                "clusters": clusters,
            }
        )
    by_season = (
        scored.groupby(["candidate", "competition_id", "season_id"])[
            [f"hindcast_minus_control_{m}" for m in METRICS]
        ]
        .mean()
        .reset_index()
    )
    reproduction = scored[scored.candidate == "M7"]
    print(
        "M7 rebuild minus archived M7 control score NLL:",
        (reproduction.control_score_nll - reproduction.archived_m7_control_score_nll).describe(),
    )
    args.tables.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.tables / "personnel_summary.csv", index=False, float_format="%.6f")
    pd.DataFrame(intervals).to_csv(
        args.tables / "personnel_intervals.csv", index=False, float_format="%.6f"
    )
    by_season.to_csv(args.tables / "personnel_seasons.csv", index=False, float_format="%.6f")
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print(summary.round(5))
    print(pd.DataFrame(intervals).round(5))


if __name__ == "__main__":
    main()
