"""Decompose the M7 forecasts of the current case-study fixtures at one cutoff."""

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np

from epl_forecast.cli import load_config
from epl_forecast.datasets import load_dataset
from epl_forecast.models import make_model
from epl_forecast.models.poisson import IndependentPoisson
from epl_forecast.schema import Fixture, fixture_id
from epl_forecast.storage import load_environment
from epl_forecast.training import training_matches

CASES = [
    ("2026-09-18", "brentford", "chelsea"),
    ("2026-09-19", "brighton-hove-albion", "arsenal"),
    ("2026-09-20", "bournemouth", "liverpool"),
    ("2026-09-20", "manchester-city", "sunderland"),
]


def probabilities(weights, means, shift=(0.0, 0.0)):
    shift = np.asarray(shift)
    return weights @ np.array(
        [IndependentPoisson(*np.exp(mean + shift)).outcome_probabilities() for mean in means]
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", default="2026-09-17")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    load_environment()
    config = load_config(Path("configs/product.toml"))
    as_of = date.fromisoformat(args.as_of)
    matches, _, manifest = load_dataset()
    specs = {spec["kind"]: spec for spec in config["models"]}
    m7 = make_model(specs["bayesian_xg_quality_tilt"])
    m7.fit(training_matches(matches, config, specs["bayesian_xg_quality_tilt"], as_of), as_of)
    m2 = make_model(specs["attack_defense_poisson"])
    m2.fit(training_matches(matches, config, specs["attack_defense_poisson"], as_of), as_of)
    season = f"{as_of.year}-{as_of.year + 1}"
    results = []
    for day, home, away in CASES:
        competition = config["competition_id"]
        fixture = Fixture(
            fixture_id(competition, season, home, away),
            competition,
            season,
            date.fromisoformat(day),
            home,
            away,
        )
        forecast = m7.predict_match(fixture)
        scores = forecast.scores
        weights = scores.weights
        means = [c.log_mean for c in scores.components]
        home_advantage = float(weights @ [m.home_advantage for m in m7.members])
        results.append(
            {
                "fixture": f"{home} v {away}",
                "match_date": day,
                "m7": list(forecast.probabilities),
                "certainty_equivalent": list(probabilities(weights, means)),
                "neutral_venue_certainty_equivalent": list(
                    probabilities(weights, means, np.array([-home_advantage, 0.0]))
                ),
                "home_advantage": home_advantage,
                "log_rate_mean": scores.log_mean.tolist(),
                "log_rate_covariance": scores.log_covariance.tolist(),
                "m2": list(m2.predict_match(fixture).probabilities),
                "teams": {team: m7.team_summary(team, season) for team in (home, away)},
            }
        )
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "cases.json").write_text(
        json.dumps({"as_of": args.as_of, "manifest": str(manifest), "cases": results}, indent=2)
    )
    print(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
