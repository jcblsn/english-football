"""Compact a season-scoring run into a committable, rescorable marginal archive."""

import argparse
import gzip
import json
from pathlib import Path

from epl_forecast.datasets import Dataset
from epl_forecast.sanctions import load_registry
from epl_forecast.season_evaluation import entry_cohorts, final_cutoff, realized_truth
from epl_forecast.storage import file_hash, load_environment, write_json

KEEP = (
    "competition_id",
    "season_id",
    "as_of",
    "simulations",
    "seed",
    "played_matches",
    "remaining_matches",
    "playoff_model",
)


def marginal(forecast):
    """Everything the scorer reads, without the per-fixture frequencies."""
    return {key: forecast[key] for key in KEEP if key in forecast} | {
        "teams": [
            {key: value for key, value in team.items() if key != "goal_difference_distribution"}
            for team in forecast["teams"]
        ]
    }


def main():
    load_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((args.evaluation / "manifest.json").read_text())
    competition = manifest["competition_id"]
    data = Dataset()
    try:
        matches = data.matches()
        sanctions = load_registry(data)
    finally:
        data.close()
    league = [m for m in matches if m.fixture.competition_id == competition]
    forecasts, truth, promoted, cohorts = [], {}, {}, {}
    for path in sorted((args.evaluation / "forecasts").glob("*.json")):
        season, origin, model = path.stem.rsplit("-", 2)
        forecast = json.loads(path.read_text())
        forecasts.append({"model_id": model, "origin": origin, "forecast": marginal(forecast)})
        if season in truth:
            continue
        season_matches = [m for m in league if m.fixture.season_id == season]
        teams = sorted(
            {t for m in season_matches for t in (m.fixture.home_team_id, m.fixture.away_team_id)}
        )
        final = sanctions.final_adjustments(competition, season, final_cutoff(season_matches))
        truth[season] = realized_truth(
            matches, competition, season, season_matches, teams, manifest["seed"], final
        )
        cohorts[season] = entry_cohorts(matches, competition, season, teams)
        promoted[season] = sorted(t for t, c in cohorts[season].items() if c != "incumbent")
    archive = {
        "schema_version": 1,
        "competition_id": competition,
        "source_manifest_sha256": file_hash(args.evaluation / "manifest.json"),
        "forecasts": forecasts,
        "truth": truth,
        "promoted": promoted,
        "entry_cohorts": cohorts,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.output, "wt") as stream:
        json.dump(archive, stream, sort_keys=True)
    write_json(
        args.output.with_suffix(".index.json"),
        {
            "archive_sha256": file_hash(args.output),
            "forecast_cells": len(forecasts),
            "seasons": sorted(truth),
            "competition_id": competition,
        },
    )
    print(args.output)


if __name__ == "__main__":
    main()
