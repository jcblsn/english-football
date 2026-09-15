"""Test a temporary mean Quality effect from realized personnel continuity."""

import argparse
import copy
import csv
import json
from collections import defaultdict
from datetime import date
from itertools import groupby
from pathlib import Path

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import logsumexp
from scipy.stats import nbinom, poisson

from epl_forecast.artifacts import execution_provenance, new_run_directory
from epl_forecast.cli import load_config, save_rows
from epl_forecast.datasets import Dataset
from epl_forecast.models import make_model
from epl_forecast.models.poisson import PoissonMixture
from epl_forecast.models.quality_tilt_scores import GammaPoissonMixture, ScoreMixture
from epl_forecast.research.personnel_mean import (
    FULL_RECENT_MINUTES,
    FULL_STARTING_MINUTES,
    REFERENCE_MINUTES,
    WINDOW,
    quality_shift,
    realized_continuity,
    shifted_scores,
)
from epl_forecast.storage import load_environment, write_json
from epl_forecast.training import training_matches

INITIAL_SEASONS = 3
MAX_KAPPA = 2.0
SEED = 20260915
COMPETITIONS = ("eng-premier-league", "eng-championship")
ENTRY_LABELS = {
    ("eng-championship", "eng-premier-league"): "promoted",
    ("eng-premier-league", "eng-championship"): "relegated",
    ("eng-league-one", "eng-championship"): "promoted",
}


def score_parameters(scores):
    components = scores.components if isinstance(scores, ScoreMixture) else [scores]
    weights = scores.weights if isinstance(scores, ScoreMixture) else np.ones(1)
    return json.dumps(
        {
            "weights": weights.tolist(),
            "components": [
                {
                    "log_mean": component.log_mean.tolist(),
                    "log_covariance": component.log_covariance.tolist(),
                    "order": int(round(np.sqrt(len(component.weights)))),
                    "dispersion": getattr(component, "dispersion", None),
                }
                for component in components
            ],
        },
        separators=(",", ":"),
    )


def scores_from_parameters(value):
    parameters = json.loads(value)
    components = []
    for item in parameters["components"]:
        kind = GammaPoissonMixture if item["dispersion"] is not None else PoissonMixture
        extra = () if item["dispersion"] is None else (item["dispersion"],)
        components.append(kind(item["log_mean"], item["log_covariance"], item["order"], *extra))
    if len(components) == 1 and parameters["weights"] == [1.0]:
        return components[0]
    return ScoreMixture(components, parameters["weights"])


def marginal_log_probability(scores, side, goals):
    if isinstance(scores, ScoreMixture):
        weights = np.full(len(scores.weights), -np.inf)
        np.log(scores.weights, out=weights, where=scores.weights > 0)
        return float(
            logsumexp(
                weights
                + [
                    marginal_log_probability(component, side, goals)
                    for component in scores.components
                ]
            )
        )
    rates = scores.home_rates if side == 0 else scores.away_rates
    if isinstance(scores, GammaPoissonMixture):
        values = nbinom.logpmf(
            goals, scores.dispersion, scores.dispersion / (scores.dispersion + rates)
        )
    else:
        values = poisson.logpmf(goals, rates)
    return float(logsumexp(np.log(scores.weights) + values))


def team_season_metadata(matches):
    appearances = {}
    competitions = defaultdict(set)
    counts = defaultdict(int)
    for match in sorted(matches, key=lambda item: (item.fixture.match_date, item.fixture.match_id)):
        fixture = match.fixture
        for team in (fixture.home_team_id, fixture.away_team_id):
            key = fixture.competition_id, fixture.season_id, team
            counts[key] += 1
            appearances[fixture.match_id, team] = counts[key]
            competitions[team, fixture.season_id].add(fixture.competition_id)
    sources = {}
    for (team, season), target_competitions in competitions.items():
        previous_start = int(season[:4]) - 1
        previous = f"{previous_start}-{previous_start + 1}"
        source_competitions = competitions.get((team, previous), set())
        for target in target_competitions:
            labels = {
                ENTRY_LABELS[source, target]
                for source in source_competitions
                if (source, target) in ENTRY_LABELS
            }
            sources[target, season, team] = next(iter(labels)) if len(labels) == 1 else "continuing"
    return appearances, sources


def predict_rows(matches, appearance_rows, data_root, start, end):
    discontinuity = realized_continuity(matches, appearance_rows)
    appearances, sources = team_season_metadata(matches)
    rows = []
    for competition in COMPETITIONS:
        config = load_config(Path("configs/product.toml"))
        config["competition_id"] = competition
        spec = copy.deepcopy(next(item for item in config["models"] if item["id"] == "M7-xg-v1"))
        spec["parameters"].update(competition_id=competition, data_root=str(data_root))
        config["models"] = [spec]
        model = make_model(spec)
        targets = sorted(
            (
                match
                for match in matches
                if match.fixture.competition_id == competition
                and start <= match.fixture.match_date < end
            ),
            key=lambda item: (item.fixture.match_date, item.fixture.match_id),
        )
        previous_season = None
        for day, games in groupby(targets, key=lambda item: item.fixture.match_date):
            games = list(games)
            if games[0].fixture.season_id != previous_season:
                previous_season = games[0].fixture.season_id
                print(f"{competition} {previous_season}", flush=True)
            model.fit(training_matches(matches, config, spec, day), as_of=day)
            for match in games:
                fixture = match.fixture
                home, away = fixture.home_team_id, fixture.away_team_id
                scores = model.predict_match(fixture).scores
                probabilities = scores.outcome_probabilities()
                d_home = discontinuity.get((fixture.match_id, home))
                d_away = discontinuity.get((fixture.match_id, away))
                rows.append(
                    {
                        "competition_id": competition,
                        "season_id": fixture.season_id,
                        "match_id": fixture.match_id,
                        "match_date": str(day),
                        "home_team_id": home,
                        "away_team_id": away,
                        "home_goals": match.home_goals,
                        "away_goals": match.away_goals,
                        "outcome": match.outcome,
                        "d_home": d_home,
                        "d_away": d_away,
                        "home_match_number": appearances[fixture.match_id, home],
                        "away_match_number": appearances[fixture.match_id, away],
                        "home_entry": sources.get(
                            (competition, fixture.season_id, home), "continuing"
                        ),
                        "away_entry": sources.get(
                            (competition, fixture.season_id, away), "continuing"
                        ),
                        "control_p_home": probabilities[0],
                        "control_p_draw": probabilities[1],
                        "control_p_away": probabilities[2],
                        "control_score_log_probability": scores.log_probability(
                            match.home_goals, match.away_goals
                        ),
                        "control_team_goal_nll": -0.5
                        * (
                            marginal_log_probability(scores, 0, match.home_goals)
                            + marginal_log_probability(scores, 1, match.away_goals)
                        ),
                        "score_parameters": score_parameters(scores),
                    }
                )
    return rows


def load_forecasts(path):
    numeric = {
        "home_goals": int,
        "away_goals": int,
        "home_match_number": int,
        "away_match_number": int,
        "d_home": float,
        "d_away": float,
        "control_p_home": float,
        "control_p_draw": float,
        "control_p_away": float,
        "control_score_log_probability": float,
        "control_team_goal_nll": float,
    }
    rows = []
    with path.open() as stream:
        for source in csv.DictReader(stream):
            row = dict(source)
            for key, conversion in numeric.items():
                row[key] = None if row[key] in ("", "None") else conversion(row[key])
            row["_scores"] = scores_from_parameters(row["score_parameters"])
            rows.append(row)
    return rows


def candidate_score_log_probability(row, kappa):
    shift = quality_shift(row["d_home"], row["d_away"], kappa)
    return shifted_scores(row["_scores"], shift).log_probability(
        row["home_goals"], row["away_goals"]
    )


def fit_kappa(rows, bounds):
    def objective(value):
        return -sum(candidate_score_log_probability(row, value) for row in rows) / len(rows)

    fit = minimize_scalar(objective, bounds=bounds, method="bounded", options={"xatol": 1e-7})
    if not fit.success:
        raise RuntimeError(f"Kappa fit failed: {fit.message}")
    return float(fit.x), float(fit.fun)


def individual_scores(row, scores):
    probabilities = np.asarray(scores.outcome_probabilities())
    outcome_index = "HDA".index(row["outcome"])
    outcome = np.eye(3)[outcome_index]
    return {
        "p_home": float(probabilities[0]),
        "p_draw": float(probabilities[1]),
        "p_away": float(probabilities[2]),
        "hda_log_loss": float(-np.log(probabilities[outcome_index])),
        "brier": float(np.sum((probabilities - outcome) ** 2)),
        "score_nll": float(-scores.log_probability(row["home_goals"], row["away_goals"])),
        "team_goal_nll": float(
            -0.5
            * (
                marginal_log_probability(scores, 0, row["home_goals"])
                + marginal_log_probability(scores, 1, row["away_goals"])
            )
        ),
    }


def calibration(rows, arm, bins=10):
    result = []
    for outcome_index, outcome in enumerate("HDA"):
        key = f"{arm}_p_{('home', 'draw', 'away')[outcome_index]}"
        probabilities = np.array([row[key] for row in rows])
        indices = np.minimum((probabilities * bins).astype(int), bins - 1)
        for index in range(bins):
            selected = indices == index
            result.append(
                {
                    "arm": arm,
                    "outcome": outcome,
                    "bin_lower": index / bins,
                    "bin_upper": (index + 1) / bins,
                    "matches": int(selected.sum()),
                    "mean_probability": None
                    if not selected.any()
                    else float(probabilities[selected].mean()),
                    "observed_frequency": None
                    if not selected.any()
                    else float(
                        np.mean(
                            [
                                row["outcome"] == outcome
                                for row, keep in zip(rows, selected, strict=True)
                                if keep
                            ]
                        )
                    ),
                }
            )
    return result


def summarize(rows, label):
    metrics = ("hda_log_loss", "brier", "score_nll", "team_goal_nll")
    result = {"scope": label, "matches": len(rows)}
    for metric in metrics:
        control = float(np.mean([row[f"control_{metric}"] for row in rows]))
        candidate = float(np.mean([row[f"candidate_{metric}"] for row in rows]))
        result[f"control_{metric}"] = control
        result[f"candidate_{metric}"] = candidate
        result[f"difference_{metric}"] = candidate - control
    return result


def paired_intervals(rows, samples, rng):
    metrics = ("hda_log_loss", "brier", "score_nll", "team_goal_nll")
    clusters = defaultdict(list)
    for row in rows:
        clusters[row["competition_id"], row["season_id"]].append(row)
    keys = sorted(clusters)
    result = {}
    for metric in metrics:
        values = np.array(
            [
                np.mean(
                    [row[f"candidate_{metric}"] - row[f"control_{metric}"] for row in clusters[key]]
                )
                for key in keys
            ]
        )
        weights = np.array([len(clusters[key]) for key in keys])
        draws = []
        for _ in range(samples):
            picked = rng.integers(0, len(keys), len(keys))
            draws.append(float(np.average(values[picked], weights=weights[picked])))
        result[metric] = {
            "clusters": len(keys),
            "interval": np.quantile(draws, [0.025, 0.975]).tolist(),
        }
    return result


def imbalance_bin(row):
    difference = abs(row["d_home"] - row["d_away"])
    if difference < 0.05:
        return "<0.05"
    if difference < 0.10:
        return "0.05-0.10"
    if difference < 0.20:
        return "0.10-0.20"
    return ">=0.20"


def report(rows, samples):
    usable = [row for row in rows if row["d_home"] is not None and row["d_away"] is not None]
    seasons = sorted({row["season_id"] for row in usable})
    target_seasons = seasons[INITIAL_SEASONS:]
    fits, scored = [], []
    for season in target_seasons:
        training = [row for row in usable if row["season_id"] < season]
        constrained, training_nll = fit_kappa(training, (0.0, MAX_KAPPA))
        unconstrained, unconstrained_nll = fit_kappa(training, (-MAX_KAPPA, MAX_KAPPA))
        fits.append(
            {
                "target_season": season,
                "training_matches": len(training),
                "kappa": constrained,
                "unconstrained_kappa": unconstrained,
                "training_score_nll": training_nll,
                "unconstrained_training_score_nll": unconstrained_nll,
                "bound_hit": min(
                    constrained,
                    MAX_KAPPA - constrained,
                    unconstrained + MAX_KAPPA,
                    MAX_KAPPA - unconstrained,
                )
                < 1e-4,
            }
        )
        for row in (item for item in usable if item["season_id"] == season):
            control = individual_scores(row, row["_scores"])
            shift = quality_shift(row["d_home"], row["d_away"], constrained)
            candidate = individual_scores(row, shifted_scores(row["_scores"], shift))
            scored.append(
                {
                    **{key: value for key, value in row.items() if not key.startswith("_")},
                    "kappa": constrained,
                    "home_log_rate_shift": float(shift[0]),
                    "away_log_rate_shift": float(shift[1]),
                    "imbalance_bin": imbalance_bin(row),
                    "imbalance_direction": (
                        "home_lower_continuity"
                        if row["d_home"] > row["d_away"]
                        else "away_lower_continuity"
                        if row["d_away"] > row["d_home"]
                        else "equal"
                    ),
                    **{f"control_{key}": value for key, value in control.items()},
                    **{f"candidate_{key}": value for key, value in candidate.items()},
                }
            )
    summaries = [summarize(scored, "all")]
    for competition in COMPETITIONS:
        selected = [row for row in scored if row["competition_id"] == competition]
        summaries.append(summarize(selected, competition))
    for season in target_seasons:
        selected = [row for row in scored if row["season_id"] == season]
        summaries.append(summarize(selected, season))
    slices = [
        ("opening-five", lambda row: min(row["home_match_number"], row["away_match_number"]) <= 5),
        ("promoted", lambda row: "promoted" in (row["home_entry"], row["away_entry"])),
        ("relegated", lambda row: "relegated" in (row["home_entry"], row["away_entry"])),
    ]
    slices.extend(
        (f"imbalance-{label}", lambda row, label=label: row["imbalance_bin"] == label)
        for label in ("<0.05", "0.05-0.10", "0.10-0.20", ">=0.20")
    )
    slices.extend(
        (f"direction-{label}", lambda row, label=label: row["imbalance_direction"] == label)
        for label in ("home_lower_continuity", "away_lower_continuity", "equal")
    )
    for label, select in slices:
        selected = [row for row in scored if select(row)]
        if selected:
            summaries.append(summarize(selected, label))
    calibration_rows = calibration(scored, "control") + calibration(scored, "candidate")
    for arm in ("control", "candidate"):
        arm_rows = [row for row in calibration_rows if row["arm"] == arm and row["matches"]]
        ece = sum(
            row["matches"]
            / len(scored)
            * abs(row["mean_probability"] - row["observed_frequency"])
            / 3
            for row in arm_rows
        )
        summaries[0][f"{arm}_classwise_ece"] = ece
    changes = sorted(
        (row["candidate_score_nll"] - row["control_score_nll"] for row in scored),
        key=abs,
        reverse=True,
    )
    total = sum(changes)
    concentration = {
        "total_score_nll_change": total,
        "largest_1_percent_share": None
        if total == 0
        else sum(changes[: max(1, len(changes) // 100)]) / total,
        "largest_5_percent_share": None
        if total == 0
        else sum(changes[: max(1, len(changes) // 20)]) / total,
        "maximum_absolute_log_rate_shift": max(abs(row["home_log_rate_shift"]) for row in scored),
        "median_absolute_log_rate_shift": float(
            np.median([abs(row["home_log_rate_shift"]) for row in scored])
        ),
    }
    return {
        "fits": fits,
        "scored": scored,
        "summaries": summaries,
        "calibration": calibration_rows,
        "paired_intervals": paired_intervals(scored, samples, np.random.default_rng(SEED)),
        "concentration": concentration,
    }


def predict_command(args):
    new_run_directory(args.output)
    data = Dataset(args.data)
    try:
        matches = data.matches()
        appearances = data.player_history()
        provenance = data.provenance()
    finally:
        data.close()
    rows = predict_rows(matches, appearances, args.data, args.start, args.end)
    save_rows(args.output / "oracle_forecasts.csv", rows)
    write_json(
        args.output / "manifest.json",
        {
            "execution": execution_provenance(),
            "window": WINDOW,
            "reference_minutes": REFERENCE_MINUTES,
            "full_recent_minutes": FULL_RECENT_MINUTES,
            "full_starting_minutes": FULL_STARTING_MINUTES,
            "start": str(args.start),
            "end": str(args.end),
            "competitions": COMPETITIONS,
            "matches": len(rows),
            "matches_with_continuity": sum(
                row["d_home"] is not None and row["d_away"] is not None for row in rows
            ),
            "data_manifest_batches": len(provenance["batches"]),
            "information": "M7 uses evidence before the match day; target starters are an oracle",
        },
    )


def report_command(args):
    new_run_directory(args.output)
    result = report(load_forecasts(args.forecasts), args.bootstrap)
    save_rows(args.output / "predictions.csv", result.pop("scored"))
    save_rows(args.output / "summary.csv", result.pop("summaries"))
    save_rows(args.output / "calibration.csv", result.pop("calibration"))
    write_json(args.output / "result.json", result)
    write_json(
        args.output / "manifest.json",
        {
            "execution": execution_provenance(),
            "forecasts": str(args.forecasts),
            "initial_seasons": INITIAL_SEASONS,
            "kappa_bounds": [0.0, MAX_KAPPA],
            "unconstrained_kappa_bounds": [-MAX_KAPPA, MAX_KAPPA],
            "bootstrap_samples": args.bootstrap,
            "bootstrap_unit": "competition-season",
            "evidence_label": "retrospective development evidence; realized starting-XI oracle",
        },
    )
    print(json.dumps(result, indent=2))


def main():
    load_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    predict_parser = commands.add_parser("predict")
    predict_parser.add_argument("--data", type=Path, required=True)
    predict_parser.add_argument("--output", type=Path, required=True)
    predict_parser.add_argument("--start", type=date.fromisoformat, default=date(2017, 8, 1))
    predict_parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 7, 1))
    predict_parser.set_defaults(func=predict_command)
    report_parser = commands.add_parser("report")
    report_parser.add_argument("--forecasts", type=Path, required=True)
    report_parser.add_argument("--output", type=Path, required=True)
    report_parser.add_argument("--bootstrap", type=int, default=2000)
    report_parser.set_defaults(func=report_command)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
