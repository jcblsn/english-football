"""Run the paired match and entry-state evaluation for National League entrants."""

import argparse
import copy
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np

from epl_forecast.artifacts import execution_provenance, new_run_directory
from epl_forecast.cli import load_config, save_rows
from epl_forecast.datasets import Dataset
from epl_forecast.evaluation import metrics, rolling_predictions
from epl_forecast.models.entry_prior import EntryPriorModel, club_features
from epl_forecast.models.promotion import completed_seasons, entry_label, season_strengths
from epl_forecast.storage import file_hash, load_environment, write_json

LEAGUE_TWO = "eng-league-two"
NATIONAL_LEAGUE = "eng-national-league"
CONTROL = "M7-national-outside-control"
CANDIDATE = "M7-national-source-candidate"


def evaluation_config(data_root: Path) -> dict:
    config = load_config(Path("configs/product.toml"))
    config["competition_id"] = LEAGUE_TWO
    source = next(spec for spec in config["models"] if spec["id"] == "M7-xg-v1")
    control, candidate = copy.deepcopy(source), copy.deepcopy(source)
    control["id"], candidate["id"] = CONTROL, CANDIDATE
    for spec in (control, candidate):
        spec["parameters"]["competition_id"] = LEAGUE_TWO
        spec["parameters"]["data_root"] = str(data_root)
    control["train_competitions"][LEAGUE_TWO] = [
        competition
        for competition in control["train_competitions"][LEAGUE_TWO]
        if competition != NATIONAL_LEAGUE
    ]
    config["models"] = [control, candidate]
    return config


def national_entrants(seasons, season: str, games=()) -> dict[str, dict]:
    games = games or seasons.get((LEAGUE_TWO, season), ())
    teams = sorted(
        {team for game in games for team in (game.fixture.home_team_id, game.fixture.away_team_id)}
    )
    return {
        team: features
        for team in teams
        if (features := club_features(seasons, LEAGUE_TWO, season, team)) is not None
        and features["source_competition"] == NATIONAL_LEAGUE
    }


def match_scopes(predictions, seasons, league_games, selected_seasons, opening_matches):
    national = {}
    continuing = set()
    source_quality = {}
    for season in selected_seasons:
        games = league_games[season]
        entrants = national_entrants(seasons, season, games)
        source = seasons.get((NATIONAL_LEAGUE, f"{int(season[:4]) - 1}-{season[:4]}"))
        if source:
            strengths = season_strengths(source)
            for team in entrants:
                state = strengths.teams[team]
                source_quality[season, team] = float(np.mean(state.mean))
        previous = seasons.get((LEAGUE_TWO, f"{int(season[:4]) - 1}-{season[:4]}"), ())
        previous_teams = {
            team
            for game in previous
            for team in (game.fixture.home_team_id, game.fixture.away_team_id)
        }
        for team in previous_teams:
            continuing.add((season, team))
        for team in entrants:
            appearances = [
                game
                for game in games
                if team in (game.fixture.home_team_id, game.fixture.away_team_id)
            ][:opening_matches]
            for index, game in enumerate(appearances, start=1):
                national.setdefault(game.fixture.match_id, []).append((team, index))
    median_quality = float(np.median(list(source_quality.values())))
    scopes = defaultdict(list)
    for row in predictions:
        scopes["all_league_two"].append(row)
        teams = (row["home_team_id"], row["away_team_id"])
        if all((row["season_id"], team) in continuing for team in teams):
            scopes["continuing_clubs"].append(row)
        for team, appearance in national.get(row["match_id"], []):
            enriched = {
                **row,
                "entrant_team_id": team,
                "entrant_appearance": appearance,
                "source_strength_slice": (
                    "strong" if source_quality[row["season_id"], team] >= median_quality else "weak"
                ),
            }
            scopes["national_entrants_first_10"].append(enriched)
            scopes[f"national_entrants_{enriched['source_strength_slice']}"].append(enriched)
            if appearance <= 5:
                scopes["national_entrants_first_5"].append(enriched)
    return scopes, median_quality


def summarize_scopes(scopes, bins):
    summaries, calibration, differences = [], [], []
    for scope, rows in sorted(scopes.items()):
        for model in (CONTROL, CANDIDATE):
            selected = [row for row in rows if row["model_id"] == model]
            if not selected:
                continue
            score, score_calibration = metrics(selected, bins)
            summaries.append({"scope": scope, "season_id": "all", "model_id": model, **score})
            calibration.extend(
                {"scope": scope, "model_id": model, **row} for row in score_calibration
            )
            for season in sorted({row["season_id"] for row in selected}):
                season_score, _ = metrics(
                    [row for row in selected if row["season_id"] == season], bins
                )
                summaries.append(
                    {"scope": scope, "season_id": season, "model_id": model, **season_score}
                )
        indexed = {
            model: {
                (row["match_id"], row.get("entrant_team_id")): row
                for row in rows
                if row["model_id"] == model
            }
            for model in (CONTROL, CANDIDATE)
        }
        common = sorted(indexed[CONTROL].keys() & indexed[CANDIDATE].keys())
        for season in ["all", *sorted({indexed[CONTROL][key]["season_id"] for key in common})]:
            keys = [
                key
                for key in common
                if season == "all" or indexed[CONTROL][key]["season_id"] == season
            ]
            if not keys:
                continue
            for metric in ("log_loss", "brier", "score_nll"):
                deltas = []
                for key in keys:
                    left, right = indexed[CONTROL][key], indexed[CANDIDATE][key]
                    if metric == "log_loss":
                        probability = {"H": "p_home", "D": "p_draw", "A": "p_away"}[left["outcome"]]
                        control_value = -np.log(left[probability])
                        candidate_value = -np.log(right[probability])
                    elif metric == "brier":
                        observed = np.array(
                            [left["outcome"] == outcome for outcome in ("H", "D", "A")]
                        )
                        control_value = np.sum(
                            (np.array([left["p_home"], left["p_draw"], left["p_away"]]) - observed)
                            ** 2
                        )
                        candidate_value = np.sum(
                            (
                                np.array([right["p_home"], right["p_draw"], right["p_away"]])
                                - observed
                            )
                            ** 2
                        )
                    else:
                        control_value = -left["score_log_probability"]
                        candidate_value = -right["score_log_probability"]
                    deltas.append(float(candidate_value - control_value))
                differences.append(
                    {
                        "scope": scope,
                        "season_id": season,
                        "metric": metric,
                        "matched_cases": len(deltas),
                        "candidate_minus_control": float(np.mean(deltas)),
                    }
                )
    return summaries, calibration, differences


def prior_scores(seasons, league_games, selected_seasons, opening_matches):
    rows = []
    diagnostics = []
    control_seasons = {key: value for key, value in seasons.items() if key[0] != NATIONAL_LEAGUE}
    for season in selected_seasons:
        games = league_games[season]
        if len(games) != 24 * 23:
            continue
        cutoff = min(game.fixture.match_date for game in games)
        entrants = national_entrants(seasons, season, games)
        labels = season_strengths(games)
        control = EntryPriorModel(control_seasons, LEAGUE_TWO, season, cutoff)
        candidate = EntryPriorModel(seasons, LEAGUE_TWO, season, cutoff)
        diagnostics.extend(
            {"model_id": model_id, **model.diagnostics()}
            for model_id, model in ((CONTROL, control), (CANDIDATE, candidate))
        )
        source_season = seasons[NATIONAL_LEAGUE, f"{int(season[:4]) - 1}-{season[:4]}"]
        source = season_strengths(source_season)
        for team in sorted(entrants):
            realized = entry_label(labels, games, team, opening_matches)
            quality = float(np.mean(source.teams[team].mean))
            for model_id, model in ((CONTROL, control), (CANDIDATE, candidate)):
                prior = model.prior(team)
                for index, dimension in enumerate(("attack", "defense")):
                    error = float(prior.mean[index] - realized[f"entry_{dimension}"])
                    variance = float(
                        prior.covariance[index, index] + realized[f"entry_{dimension}_variance"]
                    )
                    rows.append(
                        {
                            "season_id": season,
                            "team_id": team,
                            "model_id": model_id,
                            "dimension": dimension,
                            "source_quality": quality,
                            "prior_mean": float(prior.mean[index]),
                            "prior_sd": float(np.sqrt(prior.covariance[index, index])),
                            "realized": realized[f"entry_{dimension}"],
                            "squared_error": error**2,
                            "gaussian_nll": float(
                                0.5 * (np.log(2 * np.pi * variance) + error**2 / variance)
                            ),
                            "prior_source": prior.source,
                        }
                    )
    median = float(np.median([row["source_quality"] for row in rows]))
    for row in rows:
        row["source_strength_slice"] = "strong" if row["source_quality"] >= median else "weak"
    summaries = []
    for scope, selected in (
        ("all", rows),
        ("strong", [row for row in rows if row["source_strength_slice"] == "strong"]),
        ("weak", [row for row in rows if row["source_strength_slice"] == "weak"]),
    ):
        for model in (CONTROL, CANDIDATE):
            group = [row for row in selected if row["model_id"] == model]
            for metric in ("squared_error", "gaussian_nll", "prior_sd"):
                summaries.append(
                    {
                        "scope": scope,
                        "model_id": model,
                        "metric": metric,
                        "cases": len(group),
                        "mean": float(np.mean([row[metric] for row in group])),
                    }
                )
    return rows, summaries, diagnostics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seasons", nargs="+", type=int, default=list(range(2015, 2026)))
    parser.add_argument("--opening-matches", type=int, default=10)
    args = parser.parse_args()
    if args.data.resolve() == Path("data").resolve():
        raise ValueError("Use an empty R2-backed workspace, not the repository data directory")
    load_environment()
    new_run_directory(args.output)
    data = Dataset(args.data)
    try:
        matches = data.matches()
        provenance = data.provenance()
    finally:
        data.close()
    seasons = completed_seasons(matches, date(2026, 9, 15))
    grouped = defaultdict(list)
    for match in matches:
        if match.fixture.competition_id == LEAGUE_TWO:
            grouped[match.fixture.season_id].append(match)
    league_games = {
        season: tuple(
            sorted(games, key=lambda match: (match.fixture.match_date, match.fixture.match_id))
        )
        for season, games in grouped.items()
    }
    selected = [f"{year}-{year + 1}" for year in args.seasons]
    selected = [
        season
        for season in selected
        if national_entrants(seasons, season, league_games.get(season, ()))
    ]
    config = evaluation_config(args.data)
    predictions = rolling_predictions(
        matches,
        config,
        date(args.seasons[0], 7, 1),
        date(args.seasons[-1] + 1, 7, 1),
        progress=True,
    )
    scopes, median_quality = match_scopes(
        predictions, seasons, league_games, selected, args.opening_matches
    )
    summaries, calibration, differences = summarize_scopes(scopes, config["calibration_bins"])
    priors, prior_summary, diagnostics = prior_scores(
        seasons, league_games, selected, args.opening_matches
    )
    save_rows(args.output / "predictions.csv", predictions)
    save_rows(args.output / "match_summary.csv", summaries)
    save_rows(args.output / "match_calibration.csv", calibration)
    save_rows(args.output / "matched_differences.csv", differences)
    save_rows(args.output / "entry_prior_scores.csv", priors)
    save_rows(args.output / "entry_prior_summary.csv", prior_summary)
    write_json(args.output / "entry_models.json", diagnostics)
    write_json(
        args.output / "manifest.json",
        {
            "execution": execution_provenance(),
            "main_base_sha": "f3660fe78367243290706acb406055ca422f559c",
            "candidate_sha": execution_provenance()["commit"],
            "data_authority": "page324-data through an empty R2-backed workspace",
            "data_manifest": provenance,
            "configuration": config,
            "information_cutoff": "Start of match date; no same-day results",
            "matched_case_rule": "The same League Two fixtures for control and candidate",
            "selected_seasons": selected,
            "opening_matches": args.opening_matches,
            "source_quality_median": median_quality,
            "historical_evidence_label": "Retrospective development evidence",
            "limitations": [
                "The 2019-2020 and 2020-2021 National League seasons are incomplete and excluded as sources.",
                "Historical development results are not fresh confirmation.",
                "Season clusters are shown individually because the sample is small.",
            ],
            "code_hashes": {
                str(path): file_hash(path) for path in sorted(Path("src").rglob("*.py"))
            },
            "runner_hash": file_hash(Path(__file__)),
        },
    )
    primary = [
        row
        for row in differences
        if row["season_id"] == "all"
        and row["scope"] in {"national_entrants_first_10", "all_league_two"}
    ]
    print(json.dumps({"selected_seasons": selected, "primary_differences": primary}, indent=2))


if __name__ == "__main__":
    main()
