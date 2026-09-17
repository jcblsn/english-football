"""Score the M10 dynamics candidates from the rolling forecasts of `m10_rolling.py`.

Usage: uv run --with pandas --with pyarrow python scripts/research/m10_analysis.py --runs runs/m10-grid
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.special import logsumexp

ROOT = Path(__file__).resolve().parents[2]
TABLES = ROOT / "docs/experiments/m10_quality_dynamics/tables"
DIVISIONS = ("eng-premier-league", "eng-championship", "eng-league-one", "eng-league-two")
CONTROL = "r0.85-s0.09"
FIRST_SELECTION_SEASON = "2012-2013"
TEST_SEASONS = [f"{y}-{y + 1}" for y in range(2015, 2026)]
OUTCOME = {"H": 0, "D": 1, "A": 2}
MEMBERS = 3
BLOCK_DAYS = 28


def scores(p, y, score_log_probability):
    rows = np.arange(len(y))
    onehot = np.eye(3)[y]
    return pd.DataFrame(
        {
            "log_loss": -np.log(p[rows, y]),
            "brier": ((p - onehot) ** 2).sum(axis=1),
            "score_nll": -score_log_probability,
        }
    )


def load(runs):
    frames = {}
    for division in DIVISIONS:
        for path in sorted((runs / division).glob("*.parquet")):
            if path.stem.endswith("-states"):
                continue
            frames[division, path.stem] = pd.read_parquet(path)
    return frames


def candidate_names(frames):
    return sorted({name for _, name in frames})


def base_table(frames):
    """One row per match and candidate with the as-run mixture scores."""
    rows = []
    for d in frames.values():
        y = d.outcome.map(OUTCOME).to_numpy()
        p = d[["p_home", "p_draw", "p_away"]].to_numpy()
        s = scores(p, y, d.score_log_probability.to_numpy())
        rows.append(
            pd.concat(
                [
                    d[
                        [
                            "competition_id",
                            "candidate",
                            "match_id",
                            "season_id",
                            "match_date",
                            "home_team_id",
                            "away_team_id",
                            "outcome",
                            "p_home",
                            "p_draw",
                            "p_away",
                            "home_quality",
                            "away_quality",
                            "home_state_source",
                            "away_state_source",
                            "home_season_matches",
                            "away_season_matches",
                        ]
                    ].reset_index(drop=True),
                    s,
                ],
                axis=1,
            )
        )
    table = pd.concat(rows, ignore_index=True)
    table["match_date"] = pd.to_datetime(table.match_date)
    return table


def averaged(frames, names, label):
    """Average over dynamics and noise members, with weights from each filter's chronological evidence."""
    rows = []
    for division in DIVISIONS:
        parts = [frames[division, n] for n in names if (division, n) in frames]
        if len(parts) != len(names):
            continue
        base = parts[0]
        evidence = np.column_stack(
            [d[f"m{i}_log_evidence"].to_numpy() for d in parts for i in range(MEMBERS)]
        )
        # Equal prior weight for each dynamics point, shared equally by its noise members.
        log_weights = evidence - logsumexp(evidence, axis=1, keepdims=True)
        weights = np.exp(log_weights)
        p = sum(
            weights[:, k, None] * d[[f"m{i}_p_home", f"m{i}_p_draw", f"m{i}_p_away"]].to_numpy()
            for k, (d, i) in enumerate((d, i) for d in parts for i in range(MEMBERS))
        )
        lp = np.column_stack(
            [d[f"m{i}_score_log_probability"].to_numpy() for d in parts for i in range(MEMBERS)]
        )
        score = logsumexp(lp + log_weights, axis=1)
        y = base.outcome.map(OUTCOME).to_numpy()
        frame = base[["competition_id", "match_id", "season_id", "match_date", "outcome"]].copy()
        frame["candidate"] = label
        frame[["p_home", "p_draw", "p_away"]] = p
        frame = pd.concat([frame.reset_index(drop=True), scores(p, y, score)], axis=1)
        dynamics = weights.reshape(len(base), len(parts), MEMBERS).sum(axis=2)
        frame["top_dynamics"] = np.array(names)[dynamics.argmax(axis=1)]
        frame["top_weight"] = dynamics.max(axis=1)
        rows.append(frame)
    frame = pd.concat(rows, ignore_index=True)
    frame["match_date"] = pd.to_datetime(frame.match_date)
    return frame


def forward_chained(table, names, label, metric="score_nll"):
    """For each season, the candidate with the lowest pooled mean score on all earlier seasons."""
    pool = table[table.candidate.isin(names)]
    seasons = sorted(pool.season_id.unique())
    season_means = (
        pool.groupby(["candidate", "season_id"])[metric].agg(["sum", "count"]).reset_index()
    )
    chosen, rows = {}, []
    for season in seasons:
        earlier = season_means[
            (season_means.season_id < season) & (season_means.season_id >= FIRST_SELECTION_SEASON)
        ]
        if earlier.empty:
            continue
        totals = earlier.groupby("candidate")[["sum", "count"]].sum()
        best = (totals["sum"] / totals["count"]).idxmin()
        chosen[season] = best
        rows.append(pool[(pool.season_id == season) & (pool.candidate == best)])
    frame = pd.concat(rows, ignore_index=True).assign(candidate=label)
    return frame, chosen


def block_interval(diff, dates, seasons, draws=2000, seed=20260917):
    """Paired mean difference with a bootstrap of 28-day blocks inside each season."""
    frame = pd.DataFrame({"diff": diff, "season": seasons, "date": dates})
    start = frame.groupby("season").date.transform("min")
    frame["block"] = frame.season + ":" + ((frame.date - start).dt.days // BLOCK_DAYS).astype(str)
    blocks = frame.groupby("block")["diff"].agg(["sum", "count"])
    season_of = frame.groupby("block").season.first()
    rng = np.random.default_rng(seed)
    groups = [blocks[season_of == s].to_numpy() for s in season_of.unique()]
    means = []
    for _ in range(draws):
        total = np.zeros(2)
        for g in groups:
            total += g[rng.integers(len(g), size=len(g))].sum(axis=0)
        means.append(total[0] / total[1])
    return float(diff.mean()), *np.quantile(means, [0.025, 0.975])


def paired(table, candidate, control=CONTROL, mask=None):
    a = table[table.candidate == candidate].set_index("match_id")
    b = table[table.candidate == control].set_index("match_id")
    joined = a.join(b, rsuffix="_control", how="inner")
    if mask is not None:
        joined = joined[mask(joined)]
    return joined


def comparison_rows(table, candidates, slices):
    rows = []
    for candidate in candidates:
        base = paired(table, candidate)
        for slice_name, select in slices.items():
            j = base[select(base)]
            if j.empty:
                continue
            row = {"candidate": candidate, "slice": slice_name, "matches": len(j)}
            for metric in ("log_loss", "brier", "score_nll"):
                diff = j[metric] - j[f"{metric}_control"]
                if metric == "brier":
                    row[metric] = float(diff.mean())
                    continue
                mean, low, high = block_interval(
                    diff.to_numpy(), j.match_date.reset_index(drop=True), j.season_id.to_numpy()
                )
                row.update({metric: mean, f"{metric}_low": low, f"{metric}_high": high})
            rows.append(row)
    return pd.DataFrame(rows)


def stretch(frame):
    """Best power on the home/away odds with the draw probability fixed. One means no compression."""
    y = frame.outcome.map(OUTCOME).to_numpy()
    ph, pd_, pa = (frame[c].to_numpy() for c in ("p_home", "p_draw", "p_away"))
    ratio = np.log(ph / pa)

    def loss(beta):
        home = (1 - pd_) / (1 + np.exp(-beta * ratio))
        p = np.column_stack([home, pd_, 1 - pd_ - home])
        return -np.log(p[np.arange(len(y)), y]).mean()

    return float(minimize_scalar(loss, bounds=(0.5, 2.0), method="bounded").x)


def calibration_error(frame, bins=10):
    p = frame[["p_home", "p_draw", "p_away"]].to_numpy()
    y = np.eye(3)[frame.outcome.map(OUTCOME).to_numpy()]
    total = 0.0
    for k in range(3):
        index = np.minimum((p[:, k] * bins).astype(int), bins - 1)
        for b in range(bins):
            m = index == b
            if m.any():
                total += m.sum() / len(p) * abs(p[m, k].mean() - y[m, k].mean())
    return total / 3


def add_slices(table):
    control = table[table.candidate == CONTROL]
    first = control.sort_values("match_date")
    club_rows = pd.concat(
        [
            first[
                ["competition_id", "season_id", "match_date", f"{side}_team_id", f"{side}_quality"]
            ].rename(columns={f"{side}_team_id": "team_id", f"{side}_quality": "quality"})
            for side in ("home", "away")
        ]
    ).sort_values("match_date")
    opening = (
        club_rows.groupby(["competition_id", "season_id", "team_id"]).quality.first().reset_index()
    )
    opening["quintile"] = opening.groupby(["competition_id", "season_id"]).quality.transform(
        lambda q: pd.qcut(q.rank(method="first"), 5, labels=False)
    )
    lookup = opening.set_index(["competition_id", "season_id", "team_id"]).quintile
    keys = control.set_index("match_id")
    home = lookup.reindex(
        list(zip(keys.competition_id, keys.season_id, keys.home_team_id, strict=True))
    )
    away = lookup.reindex(
        list(zip(keys.competition_id, keys.season_id, keys.away_team_id, strict=True))
    )
    frame = pd.DataFrame(
        {
            "match_id": keys.index,
            "home_quintile": home.to_numpy(),
            "away_quintile": away.to_numpy(),
            "entrant_match": (
                (keys.home_state_source != "previous league state")
                | (keys.away_state_source != "previous league state")
            ).to_numpy(),
            "early": (
                keys[["home_season_matches", "away_season_matches"]].min(axis=1) < 10
            ).to_numpy(),
        }
    )
    return table.drop(
        columns=[c for c in frame.columns if c != "match_id" and c in table], errors="ignore"
    ).merge(frame, on="match_id", how="left")


def martingale(runs, names, lags=(5, 10)):
    """Regress the unexpected later change of filtered Quality on the recent change and on the level."""
    rows = []
    for division in DIVISIONS:
        for name in names:
            path = runs / division / f"{name}-states.parquet"
            if not path.exists():
                continue
            s = pd.read_parquet(path)
            s["match_date"] = pd.to_datetime(s.match_date)
            spec = json.loads((runs / "candidates.json").read_text())[name]["dynamics"]
            if "form_retention" in spec:
                continue
            s = s.sort_values(["team_id", "match_date"])
            s = s[s.season_matches.diff().fillna(1) != 0]
            s = s.drop_duplicates(["team_id", "season_id", "season_matches"])
            for lag in lags:
                g = s.groupby(["team_id", "season_id"])
                past = s.quality - g.quality.shift(lag)
                future_q = g.quality.shift(-lag)
                years = (g.match_date.shift(-lag) - s.match_date).dt.days / 365.25
                expected = s.quality * spec["quality_retention"] ** years
                surprise = future_q - expected
                m = past.notna() & surprise.notna()
                x = np.column_stack([np.ones(m.sum()), past[m], s.quality[m]])
                beta = np.linalg.lstsq(x, surprise[m], rcond=None)[0]
                rows.append(
                    {
                        "competition_id": division,
                        "candidate": name,
                        "lag_matches": lag,
                        "pairs": int(m.sum()),
                        "slope_recent_change": beta[1],
                        "slope_quality": beta[2],
                        "mean_surprise": float(surprise[m].mean()),
                    }
                )
    return pd.DataFrame(rows)


def division_mean(runs, names):
    rows = []
    for division in DIVISIONS:
        for name in names:
            path = runs / division / f"{name}-states.parquet"
            if not path.exists():
                continue
            s = pd.read_parquet(path)
            last = s[s.match_date == s.groupby("season_id").match_date.transform("max")]
            summary = last.groupby("season_id").quality.agg(["mean", "std"]).reset_index()
            rows.append(summary.assign(competition_id=division, candidate=name))
    return pd.concat(rows, ignore_index=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, default=ROOT / "runs/m10-grid")
    parser.add_argument("--output", type=Path, default=TABLES)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    frames = load(args.runs)
    names = candidate_names(frames)
    grid = [n for n in names if n.startswith("r")]
    split = [n for n in names if n.startswith("level")]
    table = base_table(frames)
    derived = []
    selections = {}
    for label, members in (("C1-FC", grid), ("C2-FC", split), ("ALL-FC", grid + split)):
        if members:
            frame, chosen = forward_chained(table, members, label)
            derived.append(frame)
            selections[label] = chosen
    for label, members in (("C1-BMA", grid), ("C2-BMA", split)):
        if members:
            derived.append(averaged(frames, members, label))
    extra = pd.concat(derived, ignore_index=True)
    table = pd.concat(
        [table, extra[[c for c in extra.columns if c in table.columns]]], ignore_index=True
    )
    table = add_slices(table)
    pd.DataFrame(
        [
            {"selection": k, "season_id": s, "candidate": c}
            for k, v in selections.items()
            for s, c in v.items()
        ]
    ).to_csv(args.output / "forward_selection.csv", index=False)

    test = table[table.season_id.isin(TEST_SEASONS)]
    overall = (
        test.groupby(["candidate", "competition_id"])[["log_loss", "brier", "score_nll"]]
        .mean()
        .reset_index()
    )
    pooled = test.groupby("candidate")[["log_loss", "brier", "score_nll"]].mean().reset_index()
    pooled["competition_id"] = "all"
    calibration = [
        {
            "candidate": c,
            "competition_id": division,
            "ece": calibration_error(g),
            "stretch": stretch(g),
        }
        for (c, division), g in test.groupby(["candidate", "competition_id"])
    ]
    summary = pd.concat([overall, pooled]).merge(
        pd.DataFrame(calibration), on=["candidate", "competition_id"], how="left"
    )
    summary.to_csv(args.output / "summary.csv", index=False)

    seasons = test.groupby(["candidate", "competition_id", "season_id"])[
        ["log_loss", "score_nll"]
    ].mean()
    control = seasons.xs(CONTROL, level="candidate")
    (seasons - control).reset_index().query("candidate != @CONTROL").to_csv(
        args.output / "season_differences.csv", index=False
    )

    candidates = [c for c in table.candidate.unique() if c != CONTROL]
    slices = {"all": lambda j: j.index == j.index}
    for division in DIVISIONS:
        slices[division] = lambda j, d=division: j.competition_id == d
    slices.update(
        {
            "EFL": lambda j: j.competition_id != "eng-premier-league",
            "entrant matches": lambda j: j.entrant_match,
            "continuing matches": lambda j: ~j.entrant_match,
            "first 10 matches": lambda j: j.early,
            "later matches": lambda j: ~j.early,
            "top-quintile club": lambda j: (j.home_quintile == 4) | (j.away_quintile == 4),
            "bottom-quintile club": lambda j: (j.home_quintile == 0) | (j.away_quintile == 0),
            "middle only": lambda j: j.home_quintile.between(1, 3) & j.away_quintile.between(1, 3),
        }
    )
    comparison_rows(test, candidates, slices).to_csv(args.output / "comparisons.csv", index=False)
    martingale(args.runs, names).to_csv(args.output / "martingale.csv", index=False)
    division_mean(args.runs, names).to_csv(args.output / "division_mean_quality.csv", index=False)
    table.to_parquet(args.runs / "scored.parquet", index=False)


if __name__ == "__main__":
    main()
