"""Market diagnostics of the M10 candidates, after the outcome evaluation. The market is not a selection criterion.

For Premier League matches 2016/17–2025/26, compare each candidate with the average pre-closing
market (the BetBrain average before 2019/20): the slope of the market directional strength on the
model directional strength, the share of the squared residual that club effects explain, and the
club effects of 2023/24–2025/26.

Usage: uv run --with pandas --with pyarrow python scripts/research/m10_market.py --candidates r0.85-s0.09 r1.00-s0.09
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from epl_forecast.datasets import Dataset
from epl_forecast.storage import load_environment

ROOT = Path(__file__).resolve().parents[2]
TABLES = ROOT / "docs/experiments/m10_quality_dynamics/tables"
FAMILIES = ("market_average_preclosing", "betbrain_average_preclosing")
RECENT = ("2023-2024", "2024-2025", "2025-2026")
PENALTY = 2.0


def market():
    load_environment()
    data = Dataset()
    try:
        rows = data.rows(
            "SELECT match_id, family, home_odds, draw_odds, away_odds FROM odds "
            "WHERE family IN ('market_average_preclosing', 'betbrain_average_preclosing') "
            "AND match_id LIKE 'eng-premier-league:%'"
        )
    finally:
        data.close()
    odds = pd.DataFrame(rows)
    odds["rank"] = odds.family.map({f: i for i, f in enumerate(FAMILIES)})
    odds = odds.sort_values("rank").drop_duplicates("match_id").set_index("match_id")
    implied = 1 / odds[["home_odds", "draw_odds", "away_odds"]].astype(float)
    implied = implied.div(implied.sum(axis=1), axis=0)
    return np.log(implied.home_odds / implied.away_odds).rename("market_direction")


def club_design(d, clubs):
    index = {c: i for i, c in enumerate(clubs)}
    x = np.zeros((len(d), len(clubs)))
    for row, (h, a) in enumerate(zip(d.home_team_id, d.away_team_id, strict=True)):
        x[row, index[h]] += 1
        x[row, index[a]] -= 1
    return x


def ridge(x, y, free):
    p = np.full(x.shape[1], PENALTY)
    p[list(free)] = 0
    return np.linalg.solve(x.T @ x + np.diag(p), x.T @ y)


def explained(x, y, free):
    beta = ridge(x, y, free)
    return 1 - ((y - x @ beta) ** 2).sum() / (y**2).sum(), beta


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, default=ROOT / "runs/m10-grid")
    parser.add_argument("--candidates", nargs="+", required=True)
    args = parser.parse_args()
    table = pd.read_parquet(args.runs / "scored.parquet")
    table = table[
        (table.competition_id == "eng-premier-league")
        & (table.season_id >= "2016-2017")
        & (table.season_id <= "2025-2026")
    ]
    direction = market()
    summaries, clubs_rows = [], []
    for candidate in args.candidates:
        d = (
            table[table.candidate == candidate]
            .join(direction, on="match_id")
            .dropna(subset=["market_direction"])
        )
        model = np.log(d.p_home / d.p_away).to_numpy()
        residual = d.market_direction.to_numpy() - model
        x = np.column_stack([np.ones(len(d)), model])
        slope = np.linalg.lstsq(x, d.market_direction.to_numpy(), rcond=None)[0][1]
        clubs = sorted(set(d.home_team_id) | set(d.away_team_id))
        scale_share, _ = explained(x, residual, free=(0, 1))
        club_share, _ = explained(
            np.column_stack([np.ones(len(d)), club_design(d, clubs)]), residual, free=(0,)
        )
        summaries.append(
            {
                "candidate": candidate,
                "matches": len(d),
                "market_slope": slope,
                "mean_squared_residual": float((residual**2).mean()),
                "scale_share": scale_share,
                "club_share": club_share,
            }
        )
        recent = d.season_id.isin(RECENT).to_numpy()
        r = d[recent]
        clubs = sorted(set(r.home_team_id) | set(r.away_team_id))
        x = np.column_stack([np.ones(len(r)), np.log(r.p_home / r.p_away), club_design(r, clubs)])
        _, beta = explained(x, residual[recent], free=(0, 1))
        clubs_rows.extend(
            {"candidate": candidate, "team_id": c, "adjusted_effect": b}
            for c, b in zip(clubs, beta[2:], strict=True)
        )
    TABLES.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(summaries).to_csv(TABLES / "market_summary.csv", index=False)
    clubs = pd.DataFrame(clubs_rows).pivot(
        index="team_id", columns="candidate", values="adjusted_effect"
    )
    clubs.sort_values(args.candidates[0]).to_csv(TABLES / "market_clubs.csv")
    print(pd.DataFrame(summaries).to_string())
    print(clubs.sort_values(args.candidates[0]).round(2).to_string())


if __name__ == "__main__":
    main()
