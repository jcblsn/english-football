"""Compare starting-XI continuity with matchday-squad continuity on the historical oracle.

Matchday-squad discontinuity is the recent minute share of players who are not in the target
matchday squad. It equals the starting-XI discontinuity minus the benched weight.
"""

import argparse
import csv
import importlib.util
from collections import defaultdict
from pathlib import Path

import numpy as np

from epl_forecast.artifacts import execution_provenance, new_run_directory
from epl_forecast.cli import save_rows
from epl_forecast.research.personnel_mean import shifted_scores
from epl_forecast.research.roster import BENCHED, CLASSES
from epl_forecast.storage import write_json

_spec = importlib.util.spec_from_file_location(
    "personnel_transition_script", Path(__file__).with_name("personnel_transition.py")
)
transition = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(transition)
pm = transition.pm

REPRESENTATIONS = ("xi", "squad")
METRICS = ("hda_log_loss", "brier", "score_nll", "team_goal_nll")
SEED = 20260917


def feature(values, representation):
    return values["d"] if representation == "xi" else values["d"] - values[BENCHED]


def imbalance(row, representation):
    return feature(row["away"], representation) - feature(row["home"], representation)


def evaluate(row, representation, kappa):
    delta = kappa * imbalance(row, representation)
    scores = pm.individual_scores(row, shifted_scores(row["_scores"], np.array([delta, -delta])))
    return delta, scores


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forecasts", type=Path, required=True)
    parser.add_argument("--components", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap", type=int, default=2000)
    args = parser.parse_args()
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
        row["home"] = components[row["match_id"], row["home_team_id"]]
        row["away"] = components[row["match_id"], row["away_team_id"]]
        row["opening_five"] = min(row["home_match_number"], row["away_match_number"]) <= 5
        rows.append(row)
    table = np.array(
        [
            transition.likelihood_grid(row["_scores"], row["home_goals"], row["away_goals"])
            for row in rows
        ]
    )
    features = {r: np.array([[imbalance(row, r)] for row in rows]) for r in REPRESENTATIONS}
    pooled = {r: float(transition.fit(table, features[r])[0]) for r in REPRESENTATIONS}
    pooled_nll = {
        r: transition.grid_nll(table, features[r][:, 0] * pooled[r]) for r in REPRESENTATIONS
    }
    control_nll = transition.grid_nll(table, np.zeros(len(rows)))
    print(f"pooled kappa {pooled}", flush=True)

    seasons = sorted({row["season_id"] for row in rows})
    fits, scored = [], []
    for season in seasons[pm.INITIAL_SEASONS :]:
        training = np.array([row["season_id"] < season for row in rows])
        kappas = {
            r: float(transition.fit(table[training], features[r][training])[0])
            for r in REPRESENTATIONS
        }
        fits.append({"target_season": season, **{f"kappa_{r}": k for r, k in kappas.items()}})
        for row in (item for item in rows if item["season_id"] == season):
            control = pm.individual_scores(row, row["_scores"])
            result = {
                "match_id": row["match_id"],
                "competition_id": row["competition_id"],
                "season_id": season,
                "opening_five": row["opening_five"],
                "xi_imbalance": imbalance(row, "xi"),
                "squad_imbalance": imbalance(row, "squad"),
                **{f"control_{m}": control[m] for m in METRICS},
            }
            for r in REPRESENTATIONS:
                delta, candidate = evaluate(row, r, kappas[r])
                result[f"{r}_delta"] = delta
                result.update({f"{r}_{m}": candidate[m] for m in METRICS})
            scored.append(result)
        print(f"{season}: {kappas}", flush=True)

    def summary(selected, label):
        result = {"scope": label, "matches": len(selected)}
        for m in METRICS:
            for r in REPRESENTATIONS:
                result[f"{r}_minus_control_{m}"] = float(
                    np.mean([row[f"{r}_{m}"] - row[f"control_{m}"] for row in selected])
                )
            result[f"squad_minus_xi_{m}"] = float(
                np.mean([row[f"squad_{m}"] - row[f"xi_{m}"] for row in selected])
            )
        return result

    scopes = [("all", lambda row: True)]
    scopes += [(c, lambda row, c=c: row["competition_id"] == c) for c in pm.COMPETITIONS]
    scopes += [("opening-five", lambda row: row["opening_five"])]
    scopes += [("after-opening-five", lambda row: not row["opening_five"])]
    for season in seasons[pm.INITIAL_SEASONS :]:
        scopes.append((season, lambda row, s=season: row["season_id"] == s))
        for c in pm.COMPETITIONS:
            scopes.append(
                (
                    f"{c}/{season}",
                    lambda row, s=season, c=c: (row["season_id"], row["competition_id"]) == (s, c),
                )
            )
    for low, high in ((0, 0.05), (0.05, 0.10), (0.10, 0.20), (0.20, 9)):
        scopes.append(
            (
                f"xi-imbalance-{low:.2f}-{high:.2f}",
                lambda row, a=low, b=high: a <= abs(row["xi_imbalance"]) < b,
            )
        )
    scopes.append(
        (
            "representations-disagree-in-sign",
            lambda row: row["xi_imbalance"] * row["squad_imbalance"] < 0,
        )
    )
    summaries = [summary([row for row in scored if select(row)], label) for label, select in scopes]
    summaries = [row for row in summaries if row["matches"]]

    clusters = defaultdict(list)
    for row in scored:
        clusters[row["competition_id"], row["season_id"]].append(row)
    keys = sorted(clusters)
    weights = np.array([len(clusters[key]) for key in keys])
    rng = np.random.default_rng(SEED)
    intervals = {}
    for comparison in ("xi_minus_control", "squad_minus_control", "squad_minus_xi"):
        left, right = comparison.split("_minus_")
        intervals[comparison] = {}
        for m in METRICS:
            values = np.array(
                [
                    np.mean([row[f"{left}_{m}"] - row[f"{right}_{m}"] for row in clusters[key]])
                    for key in keys
                ]
            )
            draws = []
            for _ in range(args.bootstrap):
                picked = rng.integers(0, len(keys), len(keys))
                draws.append(float(np.average(values[picked], weights=weights[picked])))
            intervals[comparison][m] = {
                "interval": np.quantile(draws, [0.025, 0.975]).tolist(),
                "clusters_below_zero": int(np.sum(values < 0)),
                "clusters": len(keys),
            }
    concentration = {}
    for r in REPRESENTATIONS:
        changes = sorted(
            (row[f"{r}_score_nll"] - row["control_score_nll"] for row in scored),
            key=abs,
            reverse=True,
        )
        concentration[r] = {
            "total": float(sum(changes)),
            "largest_5_percent_share": float(sum(changes[: len(changes) // 20]) / sum(changes)),
        }
    correlation = float(
        np.corrcoef(
            [row["xi_imbalance"] for row in scored], [row["squad_imbalance"] for row in scored]
        )[0, 1]
    )
    result = {
        "matches": len(rows),
        "pooled_kappa": pooled,
        "pooled_score_nll_gain": {r: control_nll - pooled_nll[r] for r in REPRESENTATIONS},
        "chronological_fits": fits,
        "intervals": intervals,
        "concentration": concentration,
        "imbalance_correlation": correlation,
    }
    save_rows(args.output / "chronological.csv", scored)
    save_rows(args.output / "summary.csv", summaries)
    write_json(args.output / "result.json", result)
    write_json(
        args.output / "manifest.json",
        {
            "execution": execution_provenance(),
            "forecasts": str(args.forecasts),
            "components": str(args.components),
            "bootstrap_samples": args.bootstrap,
            "evidence_label": "retrospective development evidence; realized matchday oracle",
        },
    )
    print(result)


if __name__ == "__main__":
    main()
