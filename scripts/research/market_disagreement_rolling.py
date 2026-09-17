"""Make rolling M2 and M7 match forecasts with state detail for the market disagreement study.

The models are the product models. The runner also calculates counterfactual probabilities from
the same posterior state. The certainty-equivalent forecast removes the Gaussian state uncertainty
of each specification. It keeps the specification mixture.
"""

import argparse
import csv
from datetime import date
from itertools import groupby
from pathlib import Path

import numpy as np

from epl_forecast.cli import load_config
from epl_forecast.datasets import load_dataset
from epl_forecast.market import devig_odds
from epl_forecast.models import make_model
from epl_forecast.models.poisson import IndependentPoisson
from epl_forecast.models.xg_quality_tilt import XG_DYNAMICS
from epl_forecast.storage import load_environment
from epl_forecast.training import training_matches

MARKETS = {
    "market_average_preclosing": "mkt",
    "market_average_closing": "close",
}


def mixture(weights, distributions):
    return np.asarray(weights) @ np.array([d.outcome_probabilities() for d in distributions])


def m7_row(model, fixture):
    forecast = model.predict_match(fixture)
    scores = forecast.scores
    weights = scores.weights
    median = [IndependentPoisson(*np.exp(c.log_mean)) for c in scores.components]
    matched = [
        IndependentPoisson(*np.exp(c.log_mean + np.diag(c.log_covariance) / 2))
        for c in scores.components
    ]
    home_advantage = np.array([m.home_advantage for m in model.members])
    home_variance = np.array([m.covariance[1, 1] for m in model.members])
    difference = np.array([1.0, -1.0])
    difference_variance = np.array(
        [difference @ c.log_covariance @ difference for c in scores.components]
    )
    row = {
        "m7_p_home": forecast.probabilities[0],
        "m7_p_draw": forecast.probabilities[1],
        "m7_p_away": forecast.probabilities[2],
        "m7_score_log_probability": None,
        "m7_log_home_rate": scores.log_mean[0],
        "m7_log_away_rate": scores.log_mean[1],
        "m7_log_home_rate_var": scores.log_covariance[0, 0],
        "m7_log_away_rate_var": scores.log_covariance[1, 1],
        "m7_log_rate_cov": scores.log_covariance[0, 1],
        "m7_difference_state_var": float(weights @ difference_variance),
        "m7_home_advantage": float(weights @ home_advantage),
        "m7_home_advantage_var": float(weights @ home_variance),
        "m7_effective_specifications": float(1 / (weights @ weights)),
    }
    for name, distributions in (("ce", median), ("cem", matched)):
        p = mixture(weights, distributions)
        row.update({f"{name}_p_home": p[0], f"{name}_p_draw": p[1], f"{name}_p_away": p[2]})
    for side, team in (("home", fixture.home_team_id), ("away", fixture.away_team_id)):
        state = model.team_summary(team, fixture.season_id)
        for key in ("quality", "tilt", "quality_sd", "tilt_sd", "state_source", "season_matches"):
            row[f"{side}_{key}"] = state[key]
    return forecast, row


def m2_row(model, fixture):
    forecast = model.predict_match(fixture)
    known = model.team_index
    return forecast, {
        "m2_p_home": forecast.probabilities[0],
        "m2_p_draw": forecast.probabilities[1],
        "m2_p_away": forecast.probabilities[2],
        "m2_log_home_rate": float(np.log(forecast.scores.home_rate)),
        "m2_log_away_rate": float(np.log(forecast.scores.away_rate)),
        "m2_home_advantage": float(model.home_advantage),
        "m2_unseen_home": fixture.home_team_id not in known,
        "m2_unseen_away": fixture.away_team_id not in known,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/product.toml"))
    parser.add_argument("--start", default="2023-08-01")
    parser.add_argument("--end", default="2026-09-17")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--quality-retention", type=float)
    parser.add_argument("--quality-sd", type=float)
    args = parser.parse_args()
    load_environment()
    config = load_config(args.config)
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    matches, odds, manifest = load_dataset()
    competition = config["competition_id"]
    quotes = {}
    for quote in odds:
        if quote["family"] in MARKETS:
            quotes[quote["match_id"], quote["family"]] = quote
    history = sorted(
        (m for m in matches if m.fixture.competition_id == competition),
        key=lambda m: (m.fixture.match_date, m.fixture.match_id),
    )
    targets = [m for m in history if start <= m.fixture.match_date < end]
    specs = {spec["id"]: spec for spec in config["models"]}
    m2_spec = next(s for s in specs.values() if s["kind"] == "attack_defense_poisson")
    m7_spec = next(s for s in specs.values() if s["kind"] == "bayesian_xg_quality_tilt")
    if args.quality_retention is not None or args.quality_sd is not None:
        dynamics = dict(XG_DYNAMICS)
        if args.quality_retention is not None:
            dynamics["quality_retention"] = args.quality_retention
        if args.quality_sd is not None:
            dynamics["quality_sd"] = args.quality_sd
        m7_spec["parameters"]["dynamics"] = dynamics
    models = {"m2": make_model(m2_spec), "m7": make_model(m7_spec)}
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    for day, games in groupby(targets, key=lambda m: m.fixture.match_date):
        games = list(games)
        print(day, flush=True)
        fitted = {}
        for key, spec in (("m2", m2_spec), ("m7", m7_spec)):
            fitted[key] = models[key].fit(training_matches(matches, config, spec, day), as_of=day)
        for match in games:
            fixture = match.fixture
            row = {
                "match_id": fixture.match_id,
                "season_id": fixture.season_id,
                "match_date": str(day),
                "home_team_id": fixture.home_team_id,
                "away_team_id": fixture.away_team_id,
                "home_goals": match.home_goals,
                "away_goals": match.away_goals,
                "outcome": match.outcome,
            }
            forecast, values = m7_row(fitted["m7"], fixture)
            values["m7_score_log_probability"] = forecast.scores.log_probability(
                match.home_goals, match.away_goals
            )
            row.update(values)
            forecast, values = m2_row(fitted["m2"], fixture)
            row.update(values)
            for family, prefix in MARKETS.items():
                quote = quotes.get((fixture.match_id, family))
                if quote is None:
                    p, implied = (None, None, None), None
                else:
                    p, implied = devig_odds(
                        quote["home_odds"], quote["draw_odds"], quote["away_odds"]
                    )
                row.update(
                    {
                        f"{prefix}_p_home": p[0],
                        f"{prefix}_p_draw": p[1],
                        f"{prefix}_p_away": p[2],
                        f"{prefix}_implied_sum": implied,
                    }
                )
            rows.append(row)
    with (args.output / "matches.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (args.output / "manifest.txt").write_text(f"{manifest}\n")
    print(f"{len(rows)} matches")


if __name__ == "__main__":
    main()
