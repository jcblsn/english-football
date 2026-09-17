"""Shared loading and transforms for the market disagreement analyses."""

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
ROLLING = ROOT / "runs/market-disagreement/rolling/matches.csv"
TABLES = ROOT / "docs/experiments/market_disagreement/tables"
SOURCES = ("m7", "ce", "cem", "m2", "mkt", "close")
OUTCOME_INDEX = {"H": 0, "D": 1, "A": 2}
HISTORY = ("2023-2024", "2024-2025", "2025-2026")


def load(path=ROLLING):
    return derive(pd.read_csv(path, parse_dates=["match_date"]))


def derive(d):
    y = d.outcome.map(OUTCOME_INDEX).to_numpy()
    for s in SOURCES:
        p = d[[f"{s}_p_home", f"{s}_p_draw", f"{s}_p_away"]].to_numpy()
        d[f"{s}_dir"] = np.log(p[:, 0] / p[:, 2])
        d[f"{s}_ll"] = -np.log(p[np.arange(len(y)), y])
    for s in ("m7", "ce", "m2", "close"):
        diff = (
            d[[f"mkt_p_{k}" for k in ("home", "draw", "away")]].to_numpy()
            - d[[f"{s}_p_{k}" for k in ("home", "draw", "away")]].to_numpy()
        )
        d[f"tv_{s}"] = 0.5 * np.abs(diff).sum(axis=1)
        d[f"ia_{s}"] = d[f"{s}_ll"] - d["mkt_ll"]
    d["resid"] = d.mkt_dir - d.m7_dir
    d["resid_m2"] = d.mkt_dir - d.m2_dir
    d["resid_ce"] = d.mkt_dir - d.ce_dir
    d["quality_gap"] = d.home_quality - d.away_quality
    d["round"] = d.groupby("season_id").match_date.rank(method="dense").astype(int)
    d["team_match_min"] = d[["home_season_matches", "away_season_matches"]].min(axis=1)
    return d


def team_rows(d, residual="resid"):
    """Two rows per match from each club's perspective; the sign follows the club."""
    rows = []
    for side, sign, other in (("home", 1.0, "away"), ("away", -1.0, "home")):
        t = pd.DataFrame(
            {
                "match_id": d.match_id,
                "season_id": d.season_id,
                "match_date": d.match_date,
                "team_id": d[f"{side}_team_id"],
                "opponent_id": d[f"{other}_team_id"],
                "venue": side,
                "resid": sign * d[residual],
                "m7_dir": sign * d.m7_dir,
                "mkt_dir": sign * d.mkt_dir,
                "m2_dir": sign * d.m2_dir,
                "quality": d[f"{side}_quality"],
                "quality_sd": d[f"{side}_quality_sd"],
                "season_matches": d[f"{side}_season_matches"],
                "state_source": d[f"{side}_state_source"],
            }
        )
        rows.append(t)
    return pd.concat(rows, ignore_index=True).sort_values(["team_id", "match_date"])


def club_design(d, clubs):
    """+1 for the home club and −1 for the away club, so effects are opponent-adjusted."""
    x = np.zeros((len(d), len(clubs)))
    index = {c: i for i, c in enumerate(clubs)}
    for row, (h, a) in enumerate(zip(d.home_team_id, d.away_team_id, strict=True)):
        x[row, index[h]] += 1
        x[row, index[a]] -= 1
    return x


def ridge(x, y, penalty, free=()):
    """Least squares with a ridge on every column except the listed free columns."""
    p = np.full(x.shape[1], penalty)
    p[list(free)] = 0
    return np.linalg.solve(x.T @ x + np.diag(p), x.T @ y)
