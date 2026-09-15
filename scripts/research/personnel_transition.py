"""Split the personnel continuity signal into roster departures and temporary absences."""

import argparse
import csv
import importlib.util
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp
from scipy.stats import poisson

from epl_forecast.artifacts import execution_provenance, new_run_directory
from epl_forecast.cli import save_rows
from epl_forecast.datasets import Dataset
from epl_forecast.live import LONDON
from epl_forecast.models.quality_tilt_scores import GammaPoissonMixture, ScoreMixture, joint_logpmf
from epl_forecast.research.personnel_mean import shifted_scores
from epl_forecast.research.roster import (
    BENCHED,
    CLASSES,
    DEPARTED,
    RETAINED,
    UNRESOLVED,
    continuity_components,
)
from epl_forecast.storage import load_environment, write_json

_spec = importlib.util.spec_from_file_location(
    "personnel_mean_script", Path(__file__).with_name("personnel_mean.py")
)
pm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pm)

GRID = np.linspace(-2.0, 2.0, 2001)
STEP = GRID[1] - GRID[0]
BOUND = 2.0
SEED = 20260916
MODELS = {
    "single": [("d",)],
    "components": [(DEPARTED,), (BENCHED, RETAINED), (UNRESOLVED,)],
    "four": [(DEPARTED,), (BENCHED,), (RETAINED,), (UNRESOLVED,)],
}
METRICS = ("hda_log_loss", "brier", "score_nll", "team_goal_nll")


def features_command(args):
    new_run_directory(args.output)
    data = Dataset(args.data)
    try:
        matches = data.matches()
        played = data.player_history()
        squads = data.rows(
            "SELECT match_id, team_id, player_id, season_id, kickoff_time, starts "
            "FROM appearances WHERE player_id IS NOT NULL"
        )
        transfers = data.rows(
            "SELECT player_id, transfer_date, from_team_id, to_team_id, transfer_type, "
            "retrieved_at FROM transfers"
        )
        provenance = data.provenance()
    finally:
        data.close()
    days = {match.fixture.match_id: match.fixture.match_date for match in matches}
    dated = []
    for row in squads:
        day = days.get(row["match_id"])
        if day is None and row["kickoff_time"] is not None:
            day = row["kickoff_time"].astimezone(LONDON).date()
        if day is not None:
            dated.append({**row, "match_date": day})
    components = continuity_components(matches, played, dated, transfers)
    rows = [
        {"match_id": match_id, "team_id": team, **values}
        for (match_id, team), values in sorted(components.items())
        if values is not None
    ]
    save_rows(args.output / "components.csv", rows)
    write_json(
        args.output / "manifest.json",
        {
            "execution": execution_provenance(),
            "team_matches": len(rows),
            "squad_rows": len(dated),
            "transfer_rows": len(transfers),
            "transfer_capture": [
                str(min(row["retrieved_at"] for row in transfers)),
                str(max(row["retrieved_at"] for row in transfers)),
            ],
            "data_manifest_batches": len(provenance["batches"]),
            "information": "retrospective diagnostic; later same-season appearances and "
            "transfers captured in September 2026 decide membership",
        },
    )
    print(f"{len(rows)} team-matches")


def likelihood_grid(scores, home, away):
    if isinstance(scores, ScoreMixture):
        weights = np.full(len(scores.weights), -np.inf)
        np.log(scores.weights, out=weights, where=scores.weights > 0)
        values = [likelihood_grid(component, home, away) for component in scores.components]
        return logsumexp(weights[:, None] + np.array(values), axis=0)
    factors = np.exp(GRID)
    home_rates = scores.home_rates[:, None] * factors
    away_rates = scores.away_rates[:, None] / factors
    if isinstance(scores, GammaPoissonMixture):
        values = joint_logpmf(home, away, home_rates, away_rates, scores.dispersion)
    else:
        values = poisson.logpmf(home, home_rates) + poisson.logpmf(away, away_rates)
    return logsumexp(np.log(scores.weights)[:, None] + values, axis=0)


def design(rows, model):
    return np.array(
        [
            [
                sum(row["away"][label] - row["home"][label] for label in labels)
                for labels in MODELS[model]
            ]
            for row in rows
        ]
    )


def grid_nll(table, delta):
    position = (np.clip(delta, -BOUND, BOUND) - GRID[0]) / STEP
    index = np.clip(np.floor(position).astype(int), 0, len(GRID) - 2)
    fraction = position - index
    selected = np.arange(len(delta))
    values = table[selected, index] * (1 - fraction) + table[selected, index + 1] * fraction
    return -float(np.mean(values))


def fit(table, features):
    start = np.zeros(features.shape[1])
    result = minimize(
        lambda value: grid_nll(table, features @ value),
        start,
        method="L-BFGS-B",
        bounds=[(-BOUND, BOUND)] * len(start),
    )
    if not result.success:
        raise RuntimeError(f"Fit failed: {result.message}")
    return result.x


def scored(row, coefficients, model):
    delta = float(design([row], model)[0] @ coefficients)
    control = pm.individual_scores(row, row["_scores"])
    candidate = pm.individual_scores(row, shifted_scores(row["_scores"], np.array([delta, -delta])))
    return {
        "model": model,
        "match_id": row["match_id"],
        "competition_id": row["competition_id"],
        "season_id": row["season_id"],
        "opening_five": row["opening_five"],
        "delta": delta,
        **{f"control_{key}": control[key] for key in METRICS},
        **{f"candidate_{key}": candidate[key] for key in METRICS},
    }


def summarize(rows, label, model):
    result = {"model": model, "scope": label, "matches": len(rows)}
    for metric in METRICS:
        result[f"difference_{metric}"] = float(
            np.mean([row[f"candidate_{metric}"] - row[f"control_{metric}"] for row in rows])
        )
    return result


def match_number_bin(number):
    return "1-5" if number <= 5 else "6-10" if number <= 10 else "11-23" if number <= 23 else "24+"


def dominant(row):
    departed = abs(row["away"][DEPARTED] - row["home"][DEPARTED])
    temporary = abs(
        row["away"][BENCHED] + row["away"][RETAINED] - row["home"][BENCHED] - row["home"][RETAINED]
    )
    unresolved = abs(row["away"][UNRESOLVED] - row["home"][UNRESOLVED])
    return max(
        ("departed", departed),
        ("temporary", temporary),
        ("unresolved", unresolved),
        key=lambda x: x[1],
    )[0]


def report_command(args):
    new_run_directory(args.output)
    components = {}
    with (args.components / "components.csv").open() as stream:
        for row in csv.DictReader(stream):
            components[row["match_id"], row["team_id"]] = {
                key: float(row[key]) for key in ("d", *CLASSES)
            }
    rows = []
    for row in pm.load_forecasts(args.forecasts):
        if row["d_home"] is None or row["d_away"] is None:
            continue
        home = components[row["match_id"], row["home_team_id"]]
        away = components[row["match_id"], row["away_team_id"]]
        for side, values in (("home", home), ("away", away)):
            if abs(values["d"] - row[f"d_{side}"]) > 1e-9:
                raise ValueError(f"Component D does not recover {row['match_id']} {side}")
            if abs(sum(values[label] for label in CLASSES) - values["d"]) > 1e-9:
                raise ValueError(f"Components do not sum to D for {row['match_id']} {side}")
        row["home"], row["away"] = home, away
        row["opening_five"] = min(row["home_match_number"], row["away_match_number"]) <= 5
        rows.append(row)
    print(f"{len(rows)} matches with components", flush=True)

    coverage = defaultdict(list)
    for row in rows:
        for side in ("home", "away"):
            key = row["competition_id"], match_number_bin(row[f"{side}_match_number"])
            coverage[key].append(row[side])
    coverage_rows = []
    for (competition, number), values in sorted(coverage.items()):
        mean_d = float(np.mean([value["d"] for value in values]))
        coverage_rows.append(
            {
                "competition_id": competition,
                "match_number": number,
                "team_matches": len(values),
                "mean_d": mean_d,
                **{
                    f"mean_{label}": float(np.mean([v[label] for v in values])) for label in CLASSES
                },
                **{
                    f"share_{label}": float(np.mean([v[label] for v in values]) / mean_d)
                    for label in CLASSES
                },
            }
        )

    table = np.array(
        [likelihood_grid(row["_scores"], row["home_goals"], row["away_goals"]) for row in rows]
    )
    print("likelihood grid ready", flush=True)
    features = {model: design(rows, model) for model in MODELS}
    pooled = {model: fit(table, features[model]).tolist() for model in MODELS}
    exact_single = pm.fit_kappa(rows, (0.0, pm.MAX_KAPPA))[0]
    print(f"pooled {pooled}; exact single kappa {exact_single}", flush=True)

    clusters = defaultdict(list)
    for index, row in enumerate(rows):
        clusters[row["competition_id"], row["season_id"]].append(index)
    keys = sorted(clusters)
    rng = np.random.default_rng(SEED)
    draws = defaultdict(list)
    for _ in range(args.bootstrap):
        picked = np.concatenate([clusters[keys[i]] for i in rng.integers(0, len(keys), len(keys))])
        for model in ("components", "four"):
            draws[model].append(fit(table[picked], features[model][picked]))
    bootstrap = {
        model: {
            "labels": ["+".join(labels) for labels in MODELS[model]],
            "estimate": pooled[model],
            "interval": np.quantile(np.array(values), [0.025, 0.975], axis=0).tolist(),
            "share_positive": np.mean(np.array(values) > 0, axis=0).tolist(),
        }
        for model, values in draws.items()
    }

    later = np.array([not row["opening_five"] for row in rows])
    out_of_slice = []
    later_fits = {}
    for model in ("single", "components"):
        coefficients = fit(table[later], features[model][later])
        later_fits[model] = coefficients.tolist()
        opening = [scored(row, coefficients, model) for row in rows if row["opening_five"]]
        out_of_slice.append(summarize(opening, "opening-five, fitted without opening five", model))

    seasons = sorted({row["season_id"] for row in rows})
    chronological, fits = [], []
    for season in seasons[pm.INITIAL_SEASONS :]:
        training = np.array([row["season_id"] < season for row in rows])
        for model in ("single", "components"):
            coefficients = fit(table[training], features[model][training])
            fits.append(
                {"target_season": season, "model": model, "coefficients": coefficients.tolist()}
            )
            for index in np.flatnonzero(np.array([row["season_id"] == season for row in rows])):
                chronological.append(
                    {**scored(rows[index], coefficients, model), "dominant": dominant(rows[index])}
                )
        print(f"{season} scored", flush=True)
    summaries = []
    for model in ("single", "components"):
        model_rows = [row for row in chronological if row["model"] == model]
        scopes = [("all", lambda row: True)]
        scopes += [
            (competition, lambda row, c=competition: row["competition_id"] == c)
            for competition in pm.COMPETITIONS
        ]
        scopes += [
            ("opening-five", lambda row: row["opening_five"]),
            ("after-opening-five", lambda row: not row["opening_five"]),
        ]
        scopes += [(season, lambda row, s=season: row["season_id"] == s) for season in seasons]
        for slice_name in ("opening-five", "after-opening-five"):
            for label in ("departed", "temporary", "unresolved"):
                scopes.append(
                    (
                        f"{slice_name}/dominant-{label}",
                        lambda row, s=slice_name, lab=label: (
                            row["opening_five"] == (s == "opening-five") and row["dominant"] == lab
                        ),
                    )
                )
        for label, select in scopes:
            chosen = [row for row in model_rows if select(row)]
            if chosen:
                summaries.append(summarize(chosen, label, model))

    anatomy = []
    for label, select in (
        ("opening-five", lambda row: row["opening_five"]),
        ("after-opening-five", lambda row: not row["opening_five"]),
    ):
        chosen = [row for row in rows if select(row)]
        anatomy.append(
            {
                "scope": label,
                "matches": len(chosen),
                "mean_absolute_d_difference": float(
                    np.mean([abs(row["d_away"] - row["d_home"]) for row in chosen])
                ),
                **{
                    f"mean_absolute_{name}_difference": float(
                        np.mean(
                            [
                                abs(sum(row["away"][x] - row["home"][x] for x in labels))
                                for row in chosen
                            ]
                        )
                    )
                    for name, labels in (
                        ("departed", (DEPARTED,)),
                        ("temporary", (BENCHED, RETAINED)),
                        ("unresolved", (UNRESOLVED,)),
                    )
                },
                "dominant_shares": {
                    name: float(np.mean([dominant(row) == name for row in chosen]))
                    for name in ("departed", "temporary", "unresolved")
                },
            }
        )

    result = {
        "matches": len(rows),
        "pooled": pooled,
        "exact_single_kappa": exact_single,
        "bootstrap": bootstrap,
        "fitted_without_opening_five": later_fits,
        "out_of_slice": out_of_slice,
        "chronological_fits": fits,
        "anatomy": anatomy,
    }
    save_rows(args.output / "coverage.csv", coverage_rows)
    save_rows(args.output / "chronological.csv", chronological)
    save_rows(args.output / "summary.csv", summaries)
    write_json(args.output / "result.json", result)
    write_json(
        args.output / "manifest.json",
        {
            "execution": execution_provenance(),
            "forecasts": str(args.forecasts),
            "components": str(args.components),
            "grid": [float(GRID[0]), float(GRID[-1]), len(GRID)],
            "bootstrap_samples": args.bootstrap,
            "evidence_label": "retrospective diagnostic; realized starting-XI oracle",
        },
    )


def main():
    load_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    features = commands.add_parser("features")
    features.add_argument("--data", type=Path, required=True)
    features.add_argument("--output", type=Path, required=True)
    features.set_defaults(func=features_command)
    report = commands.add_parser("report")
    report.add_argument("--forecasts", type=Path, required=True)
    report.add_argument("--components", type=Path, required=True)
    report.add_argument("--output", type=Path, required=True)
    report.add_argument("--bootstrap", type=int, default=300)
    report.set_defaults(func=report_command)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
