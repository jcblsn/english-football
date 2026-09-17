"""Rolling daily match forecasts for the candidates of the M10 pre-merge checks.

The method is that of `m10_rolling.py`: one fit per match day with the results available before
that day, in one division, from the start of the history. Each row also keeps the log-rate moments
and the weight of each observation-noise member, so a fixture shift can be scored without a new fit.

Usage: uv run --with pandas --with pyarrow python scripts/research/m10_premerge_rolling.py \
    --output runs/m10-premerge --competitions <division> --candidates <candidate>
"""

import argparse
import sys
import time
from datetime import date
from itertools import groupby
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from m10_variants import CANDIDATES, install  # noqa: E402

from epl_forecast.cli import load_config  # noqa: E402
from epl_forecast.competitions import COMPETITION_IDS  # noqa: E402
from epl_forecast.datasets import Dataset  # noqa: E402
from epl_forecast.models import make_model  # noqa: E402
from epl_forecast.models.poisson import PoissonMixture  # noqa: E402
from epl_forecast.models.quality_tilt_scores import ScoreMixture  # noqa: E402
from epl_forecast.storage import load_environment  # noqa: E402
from epl_forecast.training import training_matches  # noqa: E402


def config_for(competition, name, observations):
    config = load_config(Path("configs/product.toml"))
    config["competition_id"] = competition
    spec = next(s for s in config["models"] if s["kind"] == "bayesian_xg_quality_tilt")
    parameters = {k: v for k, v in spec["parameters"].items() if k != "canonical_xg"}
    parameters.update(CANDIDATES[name], observations=observations, competition_id=competition)
    return config, {**spec, "parameters": parameters}


def run(competition, name, start, end, output, matches, observations):
    config, spec = config_for(competition, name, observations)
    model = make_model(spec)
    history = sorted(
        (m for m in matches if m.fixture.competition_id == competition),
        key=lambda m: (m.fixture.match_date, m.fixture.match_id),
    )
    targets = [m for m in history if start <= m.fixture.match_date < end]
    rows = []
    clock = time.time()
    for day, games in groupby(targets, key=lambda m: m.fixture.match_date):
        games = list(games)
        try:
            training = training_matches(matches, config, spec, day)
        except ValueError:
            continue
        model.fit(training, as_of=day)
        for match in games:
            fixture = match.fixture
            row = {
                "competition_id": competition,
                "candidate": name,
                "match_id": fixture.match_id,
                "season_id": fixture.season_id,
                "match_date": str(day),
                "home_team_id": fixture.home_team_id,
                "away_team_id": fixture.away_team_id,
                "home_goals": match.home_goals,
                "away_goals": match.away_goals,
                "outcome": match.outcome,
            }
            components = []
            for index, (member, weight) in enumerate(zip(model.members, model.weights, strict=True)):
                mean, covariance = member.forecast_moments(fixture)
                components.append(PoissonMixture(mean, covariance, member.quadrature_order))
                row.update(
                    {
                        f"m{index}_weight": float(weight),
                        f"m{index}_home_mean": mean[0],
                        f"m{index}_away_mean": mean[1],
                        f"m{index}_home_variance": covariance[0, 0],
                        f"m{index}_away_variance": covariance[1, 1],
                        f"m{index}_covariance": covariance[0, 1],
                    }
                )
            scores = ScoreMixture(components, model.weights)
            p = scores.outcome_probabilities()
            row.update(
                {
                    "p_home": p[0],
                    "p_draw": p[1],
                    "p_away": p[2],
                    "score_log_probability": scores.log_probability(
                        match.home_goals, match.away_goals
                    ),
                }
            )
            for side, team in (("home", fixture.home_team_id), ("away", fixture.away_team_id)):
                state = model.team_summary(team, fixture.season_id)
                row[f"{side}_quality"] = state["quality"]
                row[f"{side}_quality_sd"] = state["quality_sd"]
                row[f"{side}_state_source"] = state["state_source"]
                row[f"{side}_season_matches"] = state["season_matches"]
            rows.append(row)
    directory = output / competition
    directory.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(directory / f"{name}.parquet", index=False)
    return competition, name, len(rows), time.time() - clock


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--competitions", nargs="+", choices=COMPETITION_IDS, default=COMPETITION_IDS
    )
    parser.add_argument("--candidates", nargs="+", default=list(CANDIDATES))
    parser.add_argument("--start", default="2010-08-01")
    parser.add_argument("--end", default="2026-09-17")
    args = parser.parse_args()
    install()
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    jobs = [
        (competition, name)
        for competition in args.competitions
        for name in args.candidates
        if not (args.output / competition / f"{name}.parquet").exists()
    ]
    if not jobs:
        return
    load_environment()
    data = Dataset()
    try:
        matches, observations = data.matches(), data.xg_observations()
    finally:
        data.close()
    for competition, name in jobs:
        print(*run(competition, name, start, end, args.output, matches, observations), flush=True)


if __name__ == "__main__":
    main()
