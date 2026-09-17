"""Fit and evaluate the chronological structural/market probability pool."""

import argparse
import csv
import gzip
from datetime import date
from pathlib import Path

from epl_forecast.artifacts import new_run_directory
from epl_forecast.evaluation import metrics
from epl_forecast.market import fit_logarithmic_pool, logarithmic_pool
from epl_forecast.storage import file_hash, write_json


def read_rows(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", newline="") as stream:
        return list(csv.DictReader(stream))


def select(rows, model):
    selected = [row for row in rows if row["model_id"] == model]
    if not selected:
        raise ValueError(f"No predictions for {model}")
    return selected


def pooled_rows(structural_rows, market_rows, weight, model_id):
    markets = {row["match_id"]: row for row in market_rows}
    output = []
    for row in structural_rows:
        market = markets.get(row["match_id"])
        if market is None:
            continue
        structural = [row[f"p_{side}"] for side in ("home", "draw", "away")]
        market_probabilities = [market[f"p_{side}"] for side in ("home", "draw", "away")]
        probabilities = logarithmic_pool(structural, market_probabilities, weight)
        output.append(
            {
                **row,
                "model_id": model_id,
                "p_home": probabilities[0],
                "p_draw": probabilities[1],
                "p_away": probabilities[2],
                "score_log_probability": None,
            }
        )
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--markets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--structural-model", default="M10-xg-v1")
    parser.add_argument("--market-model", default="market:market_average_preclosing")
    parser.add_argument("--evaluation-start", type=date.fromisoformat, default=date(2025, 7, 1))
    args = parser.parse_args()
    new_run_directory(args.output)
    structural = select(read_rows(args.predictions), args.structural_model)
    market = select(read_rows(args.markets), args.market_model)
    train_structural = [
        r for r in structural if date.fromisoformat(r["match_date"]) < args.evaluation_start
    ]
    train_ids = {r["match_id"] for r in train_structural}
    train_market = [r for r in market if r["match_id"] in train_ids]
    evaluation_structural = [
        r for r in structural if date.fromisoformat(r["match_date"]) >= args.evaluation_start
    ]
    evaluation_ids = {r["match_id"] for r in evaluation_structural}
    evaluation_market = [r for r in market if r["match_id"] in evaluation_ids]
    chronological_fit = fit_logarithmic_pool(train_structural, train_market)
    pooled = pooled_rows(
        evaluation_structural,
        evaluation_market,
        chronological_fit["market_weight"],
        "market-assisted:chronological-log-pool",
    )
    evaluation = {
        "structural": metrics(evaluation_structural)[0],
        "market": metrics(evaluation_market)[0],
        "market_assisted": metrics(pooled)[0],
    }
    final_fit = fit_logarithmic_pool(structural, market)
    write_json(
        args.output / "pool.json",
        {
            "schema_version": 1,
            "method": "logarithmic_probability_pool",
            "structural_model_id": args.structural_model,
            "market_family": args.market_model.removeprefix("market:"),
            "market_weight": final_fit["market_weight"],
            "fit_matches": final_fit["matches"],
            "fit_date_min": min(r["match_date"] for r in structural),
            "fit_date_max": max(r["match_date"] for r in structural),
            "information_horizon": "Football-Data pre-closing odds; individual historical quote times unavailable",
        },
    )
    write_json(
        args.output / "evaluation.json",
        {
            "status": "chronological historical confirmation; prospective scoring still required",
            "evaluation_start": str(args.evaluation_start),
            "training": chronological_fit,
            "evaluation": evaluation,
            "final_fit": final_fit,
            "predictions_sha256": file_hash(args.predictions),
            "markets_sha256": file_hash(args.markets),
        },
    )


if __name__ == "__main__":
    main()
