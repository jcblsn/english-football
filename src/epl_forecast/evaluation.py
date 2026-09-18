from collections import defaultdict
from datetime import date
from itertools import combinations, groupby

import numpy as np

from epl_forecast.models import make_model
from epl_forecast.models.base import Forecast
from epl_forecast.schema import OUTCOMES, Match
from epl_forecast.training import training_matches


def individual_metrics(
    probabilities: np.ndarray, outcomes: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    p = np.asarray(probabilities, dtype=float)
    y = np.asarray(outcomes, dtype=int)
    if p.shape != (len(y), 3) or len(y) == 0:
        raise ValueError("Metrics require a nonempty N by 3 probability array")
    if np.any((y < 0) | (y > 2)) or not np.all(np.isfinite(p)) or np.any(p < 0):
        raise ValueError("Invalid probabilities or outcomes")
    if not np.allclose(p.sum(axis=1), 1.0, atol=1e-10, rtol=0):
        raise ValueError("Probability rows must sum to one")
    losses = -np.log(np.maximum(p[np.arange(len(y)), y], 1e-15))
    brier = np.sum((p - np.eye(3)[y]) ** 2, axis=1)
    return losses, brier


def metrics(rows: list[dict], bins: int = 10) -> tuple[dict, list[dict]]:
    if bins < 1:
        raise ValueError("Calibration bins must be positive")
    p = np.array([[r["p_home"], r["p_draw"], r["p_away"]] for r in rows], dtype=float)
    y = np.array([OUTCOMES.index(r["outcome"]) for r in rows])
    losses, brier = individual_metrics(p, y)
    calibration = []
    ece = 0.0
    for outcome_index, outcome in enumerate(OUTCOMES):
        bin_index = np.minimum((p[:, outcome_index] * bins).astype(int), bins - 1)
        for index in range(bins):
            mask = bin_index == index
            count = int(mask.sum())
            predicted = float(p[mask, outcome_index].mean()) if count else None
            observed = float((y[mask] == outcome_index).mean()) if count else None
            if count:
                ece += count / len(rows) * abs(predicted - observed) / 3
            calibration.append(
                {
                    "outcome": outcome,
                    "bin_lower": index / bins,
                    "bin_upper": (index + 1) / bins,
                    "count": count,
                    "mean_prediction": predicted,
                    "observed_frequency": observed,
                }
            )
    score_logs = [
        float(r["score_log_probability"])
        for r in rows
        if r.get("score_log_probability") not in (None, "")
    ]
    return {
        "matches": len(rows),
        "log_loss": float(losses.mean()),
        "brier": float(brier.mean()),
        "classwise_ece": ece,
        "score_matches": len(score_logs),
        "score_nll": -float(np.mean(score_logs)) if score_logs else None,
    }, calibration


def rolling_predictions(
    matches: list[Match],
    config: dict,
    start: date,
    end: date,
    progress: bool = False,
    observations=None,
) -> list[dict]:
    if start >= end or config["train_window_days"] <= 0 or config["min_train_matches"] < 1:
        raise ValueError("Invalid evaluation dates or training limits")
    specs = config["models"]
    if not specs or len({s["id"] for s in specs}) != len(specs):
        raise ValueError("Model IDs must be nonempty and unique")
    history = sorted(
        (m for m in matches if m.fixture.competition_id == config["competition_id"]),
        key=lambda m: (m.fixture.match_date, m.fixture.match_id),
    )
    if len({m.fixture.match_id for m in matches}) != len(matches):
        raise ValueError("Duplicate matches in evaluation data")
    targets = [m for m in history if start <= m.fixture.match_date < end]
    if not targets:
        raise ValueError("No evaluation matches in the requested interval")
    predictions = []
    previous_season = None
    models = {spec["id"]: make_model(spec, observations=observations) for spec in specs}
    for forecast_date, day_iter in groupby(targets, key=lambda m: m.fixture.match_date):
        day = list(day_iter)
        if progress and day[0].fixture.season_id != previous_season:
            previous_season = day[0].fixture.season_id
            print(f"Evaluating {previous_season}", flush=True)
        for spec in specs:
            training = training_matches(matches, config, spec, forecast_date)
            known_teams = {
                team
                for m in training
                for team in (m.fixture.home_team_id, m.fixture.away_team_id)
                if m.fixture.competition_id == config["competition_id"]
            }
            model = models[spec["id"]].fit(training, as_of=forecast_date)
            for match in day:
                forecast = model.predict_match(match.fixture)
                row = {
                    "model_id": spec["id"],
                    "match_id": match.fixture.match_id,
                    "season_id": match.fixture.season_id,
                    "match_date": str(forecast_date),
                    "forecast_as_of": str(forecast_date),
                    "train_matches": len(training),
                    "train_primary_matches": sum(
                        m.fixture.competition_id == config["competition_id"] for m in training
                    ),
                    "train_date_min": str(training[0].fixture.match_date),
                    "train_date_max": str(training[-1].fixture.match_date),
                    "home_team_id": match.fixture.home_team_id,
                    "away_team_id": match.fixture.away_team_id,
                    "unseen_home": match.fixture.home_team_id not in known_teams,
                    "unseen_away": match.fixture.away_team_id not in known_teams,
                    "outcome": match.outcome,
                    "home_goals": match.home_goals,
                    "away_goals": match.away_goals,
                    "p_home": float(forecast.probabilities[0]),
                    "p_draw": float(forecast.probabilities[1]),
                    "p_away": float(forecast.probabilities[2]),
                    "score_log_probability": None
                    if forecast.scores is None
                    else forecast.scores.log_probability(match.home_goals, match.away_goals),
                }
                if forecast.scores is not None and hasattr(forecast.scores, "home_rate"):
                    from epl_forecast.models.quality_tilt_scores import score_diagnostics

                    row.update(score_diagnostics(forecast.scores))
                if hasattr(model, "weights") and hasattr(model, "members"):
                    row["effective_specifications"] = float(1 / (model.weights @ model.weights))
                if hasattr(model, "team_summary"):
                    row.update(
                        {
                            "log_home_rate_mean": float(forecast.scores.log_mean[0]),
                            "log_away_rate_mean": float(forecast.scores.log_mean[1]),
                            "log_home_rate_variance": float(forecast.scores.log_covariance[0, 0]),
                            "log_away_rate_variance": float(forecast.scores.log_covariance[1, 1]),
                            "log_rate_covariance": float(forecast.scores.log_covariance[0, 1]),
                        }
                    )
                    for side, team in (
                        ("home", match.fixture.home_team_id),
                        ("away", match.fixture.away_team_id),
                    ):
                        state = model.team_summary(team, match.fixture.season_id)
                        row.update(
                            {
                                f"{side}_{key}": value
                                for key, value in state.items()
                                if key != "team_id"
                            }
                        )
                predictions.append(row)
    return predictions


def market_predictions(predictions: list[dict], odds: list[dict]) -> list[dict]:
    targets = {row["match_id"]: row for row in predictions}
    results = []
    seen = set()
    for quote in odds:
        match_id = quote["match_id"]
        if match_id not in targets:
            continue
        key = match_id, quote["family"]
        if key in seen:
            raise ValueError(f"Duplicate market quote: {key}")
        seen.add(key)
        prices = np.array([float(quote[k]) for k in ("home_odds", "draw_odds", "away_odds")])
        if not np.all(np.isfinite(prices)) or np.any(prices <= 1):
            raise ValueError("Invalid decimal market odds")
        implied = 1 / prices
        p = implied / implied.sum()
        Forecast(tuple(p))
        target = targets[match_id]
        results.append(
            {
                "model_id": f"market:{quote['family']}",
                "match_id": match_id,
                "season_id": target["season_id"],
                "match_date": target["match_date"],
                "outcome": target["outcome"],
                "p_home": float(p[0]),
                "p_draw": float(p[1]),
                "p_away": float(p[2]),
                "score_log_probability": None,
                "implied_sum": float(implied.sum()),
                "forecast_as_of": None,
                "horizon": "source pre-match odds; individual collection time unavailable",
            }
        )
    return results


def paired_comparison(
    reference: list[dict], candidate: list[dict], samples: int, seed: int
) -> dict:
    if samples < 1:
        raise ValueError("bootstrap_samples must be positive")
    ref = {row["match_id"]: row for row in reference}
    other = {row["match_id"]: row for row in candidate}
    ids = sorted(ref.keys() & other.keys())
    if not ids:
        raise ValueError("No common predictions to compare")
    blocks = defaultdict(list)
    deltas = []
    for match_id in ids:
        row, second = ref[match_id], other[match_id]
        if row["outcome"] != second["outcome"]:
            raise ValueError("Compared forecasts disagree on the observed outcome")
        key = ("p_home", "p_draw", "p_away")[OUTCOMES.index(row["outcome"])]
        delta = -np.log(max(float(second[key]), 1e-15)) + np.log(max(float(row[key]), 1e-15))
        played_on = date.fromisoformat(row["match_date"])
        season_start = date(int(row["season_id"][:4]), 7, 1)
        blocks[(row["season_id"], (played_on - season_start).days // 28)].append(delta)
        deltas.append(delta)
    values = list(blocks.values())
    sums = np.array([sum(block) for block in values])
    counts = np.array([len(block) for block in values])
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(values), size=(samples, len(values)))
    draws = sums[indices].sum(axis=1) / counts[indices].sum(axis=1)
    lower, upper = np.quantile(draws, [0.025, 0.975])
    return {
        "reference": reference[0]["model_id"],
        "candidate": candidate[0]["model_id"],
        "matches": len(ids),
        "delta_log_loss": float(np.mean(deltas)),
        "ci_lower": float(lower),
        "ci_upper": float(upper),
        "blocks": len(values),
        "method": (
            "paired 28-day blocks within seasons, pooled block bootstrap; negative favors candidate"
        ),
    }


def summarize(predictions: list[dict], markets: list[dict], config: dict) -> dict:
    groups = defaultdict(list)
    for row in predictions:
        groups[row["model_id"]].append(row)
    market_groups = defaultdict(list)
    for row in markets:
        market_groups[row["model_id"]].append(row)
    overall, seasons, calibration = [], [], []
    for model_id, rows in (groups | market_groups).items():
        score, bins = metrics(rows, config["calibration_bins"])
        overall.append({"model_id": model_id, **score})
        calibration.extend({"model_id": model_id, **bin_row} for bin_row in bins)
        for season_id in sorted({r["season_id"] for r in rows}):
            score, _ = metrics(
                [r for r in rows if r["season_id"] == season_id], config["calibration_bins"]
            )
            seasons.append({"model_id": model_id, "season_id": season_id, **score})
    matched = []
    for market_id, rows in market_groups.items():
        ids = {r["match_id"] for r in rows}
        for model_id, model_rows in (groups | {market_id: rows}).items():
            score, _ = metrics(
                [r for r in model_rows if r["match_id"] in ids], config["calibration_bins"]
            )
            matched.append({"market_subset": market_id, "model_id": model_id, **score})
    bootstrap_samples = config.get("bootstrap_samples", 0)
    if type(bootstrap_samples) is not int or bootstrap_samples < 0:
        raise ValueError("bootstrap_samples must be a nonnegative integer")
    comparisons = [
        paired_comparison(groups[a], groups[b], config["bootstrap_samples"], config["seed"])
        for a, b in combinations(groups, 2)
        if bootstrap_samples
    ]
    for model_rows in groups.values():
        for market_rows in market_groups.values():
            if bootstrap_samples:
                comparisons.append(
                    paired_comparison(model_rows, market_rows, bootstrap_samples, config["seed"])
                )
    return {
        "overall": overall,
        "by_season": seasons,
        "calibration": calibration,
        "market_matched": matched,
        "paired_comparisons": comparisons,
    }
