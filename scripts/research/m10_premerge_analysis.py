"""Compare the rolling match forecasts of the pre-merge candidates with M10 and M7.

Test seasons 2015/16–2025/26, with the partial 2026/27 season separate. The intervals resample
28-day blocks in each season. A club match number is the smaller of the two clubs' numbers.

Usage: uv run --with pandas --with pyarrow python scripts/research/m10_premerge_analysis.py \
    --rolling runs/m10-premerge --tables <directory>
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

DIVISIONS = ("eng-premier-league", "eng-championship", "eng-league-one", "eng-league-two")
NAMES = dict(zip(DIVISIONS, ("PL", "Ch", "L1", "L2"), strict=True))
COMPARISONS = (("M10", "M7"), ("E1", "M10"), ("S1", "M10"), ("S2", "M10"))
SEED = 20260917


def load(rolling, candidate):
    frames = []
    for division in DIVISIONS:
        path = rolling / division / f"{candidate}.parquet"
        if path.exists():
            frames.append(pd.read_parquet(path))
    frame = pd.concat(frames)
    p = np.select(
        [frame.outcome == "H", frame.outcome == "D"], [frame.p_home, frame.p_draw], frame.p_away
    )
    observed = np.stack([frame.outcome == o for o in "HDA"], axis=1).astype(float)
    probabilities = frame[["p_home", "p_draw", "p_away"]].to_numpy()
    frame["log_loss"] = -np.log(p)
    frame["score_nll"] = -frame.score_log_probability
    frame["brier"] = ((probabilities - observed) ** 2).sum(axis=1)
    frame["club_match"] = np.minimum(frame.home_season_matches, frame.away_season_matches) + 1
    frame["entrant"] = (frame.home_state_source != "previous league state") | (
        frame.away_state_source != "previous league state"
    )
    return frame.set_index("match_id")


def block_interval(frame, column, draws=2000):
    dates = pd.to_datetime(frame.match_date)
    start = dates.groupby(frame.season_id).transform("min")
    blocks = frame.assign(block=((dates - start).dt.days // 28))
    totals = blocks.groupby(["season_id", "block"])[column].agg(["sum", "count"])
    rng = np.random.default_rng(SEED)
    sums, counts = np.zeros(draws), np.zeros(draws)
    for _, season in totals.groupby(level=0):
        picks = rng.integers(len(season), size=(draws, len(season)))
        sums += season["sum"].to_numpy()[picks].sum(axis=1)
        counts += season["count"].to_numpy()[picks].sum(axis=1)
    return np.quantile(sums / counts, [0.025, 0.975])


def slices(frame):
    efl = frame.competition_id != "eng-premier-league"
    result = {"All": frame.index == frame.index}
    for division in DIVISIONS:
        result[NAMES[division]] = frame.competition_id == division
    result["EFL"] = efl
    result["Entrant matches"] = frame.entrant
    result["Continuing matches"] = ~frame.entrant
    for low, high in ((1, 5), (6, 10), (11, 20), (21, 99)):
        phase = frame.club_match.between(low, high)
        result[f"Club match {low}-{high}"] = phase
        result[f"PL club match {low}-{high}"] = phase & ~efl
        result[f"EFL club match {low}-{high}"] = phase & efl
    result["Entrant matches, club match 1-5"] = frame.entrant & frame.club_match.le(5)
    result["Entrant matches, club match 1-10"] = frame.entrant & frame.club_match.le(10)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rolling", type=Path, required=True)
    parser.add_argument("--tables", type=Path, required=True)
    args = parser.parse_args()
    candidates = {name: load(args.rolling, name) for name in ("M7", "M10", "E1", "S1", "S2")}
    rows, seasons = [], []
    for left, right in COMPARISONS:
        joined = candidates[left].join(
            candidates[right][["log_loss", "score_nll", "brier"]], rsuffix="_right", how="inner"
        )
        for metric in ("log_loss", "score_nll", "brier"):
            joined[f"d_{metric}"] = joined[metric] - joined[f"{metric}_right"]
        for period, selection in (
            ("test", joined.season_id.between("2015-2016", "2025-2026")),
            ("2026/27", joined.season_id == "2026-2027"),
        ):
            part = joined[selection]
            for scope, mask in slices(part).items():
                subset = part[mask]
                if subset.empty:
                    continue
                row = {
                    "comparison": f"{left} minus {right}",
                    "period": period,
                    "scope": scope,
                    "matches": len(subset),
                }
                for metric in ("log_loss", "score_nll", "brier"):
                    row[metric] = subset[f"d_{metric}"].mean()
                    if period == "test" and metric != "brier":
                        row[f"{metric}_low"], row[f"{metric}_high"] = block_interval(
                            subset, f"d_{metric}"
                        )
                rows.append(row)
        test = joined[joined.season_id.between("2015-2016", "2025-2026")]
        effects = (
            test.groupby(["competition_id", "season_id"])[["d_log_loss", "d_score_nll"]]
            .mean()
            .reset_index()
        )
        effects["comparison"] = f"{left} minus {right}"
        seasons.append(effects)
    summary = pd.DataFrame(rows)
    args.tables.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.tables / "rolling_comparisons.csv", index=False, float_format="%.6f")
    pd.concat(seasons).to_csv(
        args.tables / "rolling_season_effects.csv", index=False, float_format="%.6f"
    )
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    shown = summary.copy()
    for column in ("log_loss", "score_nll", "brier", "log_loss_low", "log_loss_high"):
        shown[column] = shown[column] * 1000
    print(shown.round(2).to_string())


if __name__ == "__main__":
    main()
