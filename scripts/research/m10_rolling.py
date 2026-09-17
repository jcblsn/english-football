"""Rolling daily match forecasts for the M10 Quality dynamics candidates.

Each job fits one dynamics candidate in one division from the start of the history and forecasts
every match with the results available before its match day. The output keeps the forecast of each
observation-noise member and its chronological log evidence, so a selection or an average over
dynamics can be scored later without a new fit. It also keeps the Quality of every club in the
division on each match day.
"""

import argparse
import json
import time
from datetime import date
from itertools import groupby
from pathlib import Path

import pandas as pd

from epl_forecast.cli import load_config
from epl_forecast.competitions import COMPETITION_IDS
from epl_forecast.datasets import Dataset
from epl_forecast.models import make_model
from epl_forecast.storage import load_environment
from epl_forecast.training import training_matches

M7_DYNAMICS = {
    "quality_retention": 0.85,
    "quality_sd": 0.09,
    "tilt_retention": 0.5,
    "tilt_sd": 0.07,
}
DATA = {}


def grid_candidates():
    candidates = {}
    for retention in (0.85, 0.95, 1.0):
        for sd in (0.06, 0.09, 0.12):
            name = f"r{retention:.2f}-s{sd:.2f}"
            candidates[name] = {
                "dynamics": {**M7_DYNAMICS, "quality_retention": retention, "quality_sd": sd}
            }
    pairs = [(0.04, 0.10), (0.04, 0.15), (0.06, 0.10), (0.06, 0.15)]
    # Amendment: one step outward from the first selection, which was at the grid edge.
    pairs += [(0.06, 0.07), (0.08, 0.07), (0.08, 0.10)]
    for level_sd, form_sd in pairs:
        candidates[f"level-s{level_sd:.2f}-form-s{form_sd:.2f}"] = {
            "dynamics": {
                **M7_DYNAMICS,
                "quality_retention": 1.0,
                "quality_sd": level_sd,
                "form_retention": 0.3,
                "form_sd": form_sd,
            }
        }
    return candidates


CANDIDATES = grid_candidates()


def config_for(competition):
    config = load_config(Path("configs/product.toml"))
    config["competition_id"] = competition
    spec = next(s for s in config["models"] if s["kind"] == "bayesian_xg_quality_tilt")
    spec["parameters"]["competition_id"] = competition
    return config, spec


def run(job):
    competition, name, start, end, output = job
    matches, observations = DATA["matches"], DATA["observations"]
    config, spec = config_for(competition)
    parameters = {k: v for k, v in spec["parameters"].items() if k != "canonical_xg"}
    parameters.update(CANDIDATES[name], observations=observations)
    spec = {**spec, "parameters": parameters}
    model = make_model(spec)
    history = sorted(
        (m for m in matches if m.fixture.competition_id == competition),
        key=lambda m: (m.fixture.match_date, m.fixture.match_id),
    )
    targets = [m for m in history if start <= m.fixture.match_date < end]
    rows, states = [], []
    clock = time.time()
    for day, games in groupby(targets, key=lambda m: m.fixture.match_date):
        games = list(games)
        try:
            training = training_matches(matches, config, spec, day)
        except ValueError:
            continue
        model.fit(training, as_of=day)
        evidence = [m.log_evidence for m in model.members]
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
            forecast = model.predict_match(fixture)
            row.update(
                {
                    "p_home": forecast.probabilities[0],
                    "p_draw": forecast.probabilities[1],
                    "p_away": forecast.probabilities[2],
                    "score_log_probability": forecast.scores.log_probability(
                        match.home_goals, match.away_goals
                    ),
                    "log_home_rate": forecast.scores.log_mean[0],
                    "log_away_rate": forecast.scores.log_mean[1],
                }
            )
            for index, member in enumerate(model.members):
                scores = member.score_distribution(fixture)
                p = scores.outcome_probabilities()
                row.update(
                    {
                        f"m{index}_p_home": p[0],
                        f"m{index}_p_draw": p[1],
                        f"m{index}_p_away": p[2],
                        f"m{index}_score_log_probability": scores.log_probability(
                            match.home_goals, match.away_goals
                        ),
                        f"m{index}_log_evidence": evidence[index],
                    }
                )
            for side, team in (("home", fixture.home_team_id), ("away", fixture.away_team_id)):
                state = model.team_summary(team, fixture.season_id)
                for key in ("quality", "quality_sd", "tilt", "state_source", "season_matches"):
                    row[f"{side}_{key}"] = state[key]
                for key in ("quality_level", "quality_form"):
                    row[f"{side}_{key}"] = state.get(key)
            rows.append(row)
        season = games[0].fixture.season_id
        teams = sorted(
            {
                t
                for m in history
                if m.fixture.season_id == season
                for t in (m.fixture.home_team_id, m.fixture.away_team_id)
            }
        )
        for team in teams:
            state = model.team_summary(team, season)
            states.append(
                {
                    "match_date": str(day),
                    "season_id": season,
                    "team_id": team,
                    "quality": state["quality"],
                    "quality_sd": state["quality_sd"],
                    "tilt": state["tilt"],
                    "season_matches": state["season_matches"],
                    "state_source": state["state_source"],
                    "quality_level": state.get("quality_level"),
                    "quality_form": state.get("quality_form"),
                }
            )
    directory = output / competition
    directory.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(directory / f"{name}.parquet", index=False)
    pd.DataFrame(states).to_parquet(directory / f"{name}-states.parquet", index=False)
    return competition, name, len(rows), time.time() - clock


def load():
    load_environment()
    data = Dataset()
    try:
        DATA["matches"] = data.matches()
        DATA["observations"] = data.xg_observations()
        DATA["manifest"] = data.provenance()
    finally:
        data.close()


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
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "candidates.json").write_text(json.dumps(CANDIDATES, indent=2))
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    jobs = [
        (competition, name, start, end, args.output)
        for competition in args.competitions
        for name in args.candidates
        if not (args.output / competition / f"{name}.parquet").exists()
    ]
    if jobs:
        load()
    for job in jobs:
        print(*run(job), flush=True)


if __name__ == "__main__":
    main()
