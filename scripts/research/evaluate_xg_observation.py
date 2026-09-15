"""Paired chronological match evaluation of provider xG observations in M7.

`predict` runs one arm with daily refits and results before each match day only.
`report` compares the arms on identical matches. Run each arm in its own process
and its own empty workspace, then run `report` once.
"""

import argparse
import copy
import csv
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from epl_forecast.artifacts import execution_provenance
from epl_forecast.cli import load_config, save_rows
from epl_forecast.datasets import Dataset
from epl_forecast.evaluation import metrics, paired_comparison, rolling_predictions
from epl_forecast.models.xg_observation import chance_rows
from epl_forecast.models.xg_quality_tilt import calibrated_scale
from epl_forecast.storage import load_environment, write_json

PL, CHAMPIONSHIP = "eng-premier-league", "eng-championship"
UNDERSTAT = {"provider": "understat"}
API = {PL: {"provider": "api_football", "competitions": [PL]}}
API[CHAMPIONSHIP] = {"provider": "api_football", "competitions": [CHAMPIONSHIP]}
RAW, CALIBRATED = {"api_football": 1.0}, {"api_football": "calibrated"}
ARMS = {
    PL: {
        "goals-only": {"xg_sources": []},
        "understat": {},
        "api-raw": {"xg_sources": [API[PL]], "provider_scales": RAW},
        "api-calibrated": {"xg_sources": [API[PL]], "provider_scales": CALIBRATED},
    },
    CHAMPIONSHIP: {
        "control": {},
        "api-raw": {"xg_sources": [UNDERSTAT, API[CHAMPIONSHIP]], "provider_scales": RAW},
        "api-calibrated": {
            "xg_sources": [UNDERSTAT, API[CHAMPIONSHIP]],
            "provider_scales": CALIBRATED,
        },
    },
}
CONTROL = {PL: "goals-only", CHAMPIONSHIP: "control"}
DISAGREEMENT = 1.5
OPENING = 5
FLOATS = ("p_home", "p_draw", "p_away", "score_log_probability", "expected_home_goals")
FLOATS += ("expected_away_goals",)


def predict(args):
    config = load_config(Path("configs/product.toml"))
    config["competition_id"] = args.competition
    spec = copy.deepcopy(next(s for s in config["models"] if s["id"] == "M7-xg-v1"))
    spec["id"] = f"M7-{args.arm}"
    spec["parameters"].update(
        competition_id=args.competition,
        data_root=str(args.data),
        **ARMS[args.competition][args.arm],
    )
    config["models"] = [spec]
    data = Dataset(args.data)
    try:
        matches, provenance = data.matches(), data.provenance()
    finally:
        data.close()
    args.output.mkdir(parents=True, exist_ok=True)
    rows = rolling_predictions(matches, config, args.start, args.end, progress=True)
    save_rows(args.output / f"predictions-{args.arm}.csv", rows)
    write_json(
        args.output / f"manifest-{args.arm}.json",
        {
            "execution": execution_provenance(),
            "competition_id": args.competition,
            "arm": args.arm,
            "specification": spec,
            "start": str(args.start),
            "end": str(args.end),
            "matches": len(rows),
            "data_manifest_batches": len(provenance["batches"]),
            "information": "daily refit; results and xG available on the next day",
        },
    )


def read_predictions(path):
    with path.open() as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        for key in FLOATS:
            if row.get(key) not in (None, ""):
                row[key] = float(row[key])
    return rows


def slices(matches, competition, api_rows):
    """Match IDs in each prespecified slice."""
    ordered = sorted(matches, key=lambda m: (m.fixture.match_date, m.fixture.match_id))
    members = defaultdict(set)
    for match in ordered:
        f = match.fixture
        members[f.competition_id, f.season_id].update((f.home_team_id, f.away_team_id))
    appearances, previous_gap = defaultdict(int), {}
    result = defaultdict(set)
    for match in ordered:
        f = match.fixture
        if f.competition_id != competition:
            continue
        prior_season = f"{int(f.season_id[:4]) - 1}-{f.season_id[:4]}"
        row = api_rows.get(f.match_id)
        for side, team in enumerate((f.home_team_id, f.away_team_id)):
            appearances[team, f.season_id] += 1
            if appearances[team, f.season_id] <= OPENING:
                result["opening_five"].add(f.match_id)
            if team not in members[competition, prior_season]:
                result["entrant_club"].add(f.match_id)
            if previous_gap.get(team, 0) >= DISAGREEMENT:
                result["after_goal_xg_disagreement"].add(f.match_id)
            if row is not None:
                goals, xg = (row[2], row[4]) if side == 0 else (row[3], row[5])
                previous_gap[team] = abs(goals - xg)
            else:
                previous_gap[team] = 0
    return result


def score_deltas(control, candidate, ids):
    deltas = defaultdict(list)
    for match_id in ids:
        a, b = control[match_id], candidate[match_id]
        key = ("p_home", "p_draw", "p_away")["HDA".index(a["outcome"])]
        deltas["log_loss"].append(np.log(a[key]) - np.log(b[key]))
        outcome = np.eye(3)["HDA".index(a["outcome"])]
        pa = np.array([a["p_home"], a["p_draw"], a["p_away"]])
        pb = np.array([b["p_home"], b["p_draw"], b["p_away"]])
        deltas["brier"].append(np.sum((pb - outcome) ** 2) - np.sum((pa - outcome) ** 2))
        deltas["score_nll"].append(a["score_log_probability"] - b["score_log_probability"])
        deltas["max_probability_change"].append(float(np.abs(pb - pa).max()))
        deltas["expected_goals_change"].append(
            abs(b["expected_home_goals"] - a["expected_home_goals"])
            + abs(b["expected_away_goals"] - a["expected_away_goals"])
        )
    return {key: float(np.mean(values)) for key, values in deltas.items()} | {"matches": len(ids)}


def report(args):
    control_arm = CONTROL[args.competition]
    arms = {
        path.stem.removeprefix("predictions-"): read_predictions(path)
        for path in sorted(args.output.glob("predictions-*.csv"))
    }
    if control_arm not in arms:
        raise ValueError(f"The control arm {control_arm} has no predictions")
    indexed = {arm: {r["match_id"]: r for r in rows} for arm, rows in arms.items()}
    ids = sorted(set.intersection(*(set(rows) for rows in indexed.values())))
    data = Dataset(args.data)
    try:
        matches = data.matches()
        api_rows = chance_rows(data.api_xg_process([args.competition]))
    finally:
        data.close()
    groups = slices(matches, args.competition, api_rows)
    season_of = {i: indexed[control_arm][i]["season_id"] for i in ids}
    seasons = sorted(set(season_of.values()))
    scopes = {"all": ids} | {s: [i for i in ids if season_of[i] == s] for s in seasons}
    scopes |= {name: [i for i in ids if i in members] for name, members in groups.items()}

    summary, paired, uncertainty = [], [], []
    for scope, selected in scopes.items():
        if not selected:
            continue
        for arm, rows in indexed.items():
            score, _ = metrics([rows[i] for i in selected], args.bins)
            summary.append({"scope": scope, "arm": arm, **score})
        for arm in arms:
            if arm == control_arm:
                continue
            paired.append(
                {
                    "scope": scope,
                    "control": control_arm,
                    "candidate": arm,
                    **score_deltas(indexed[control_arm], indexed[arm], selected),
                }
            )
    for arm, rows in indexed.items():
        keys = [k for k in rows[ids[0]] if k.endswith("_sd") and k.startswith(("home_", "away_"))]
        for season in seasons:
            selected = [rows[i] for i in scopes[season]]
            uncertainty.append(
                {"arm": arm, "season_id": season}
                | {k: float(np.mean([float(r[k]) for r in selected])) for k in keys}
            )
    intervals = [
        paired_comparison(
            [indexed[control_arm][i] | {"model_id": control_arm} for i in ids],
            [indexed[arm][i] | {"model_id": arm} for i in ids],
            args.bootstrap,
            20260915,
        )
        for arm in arms
        if arm != control_arm
    ]
    scales, day = [], args.start
    while day < args.end:
        scales.append(
            {
                "as_of": str(day),
                "api_matches": sum(r[1] <= day for r in api_rows.values()),
                "calibrated_scale": calibrated_scale(api_rows, "api_football", day),
            }
        )
        day = (day.replace(day=1) + timedelta(days=32)).replace(day=1)
    save_rows(args.output / "summary.csv", summary)
    save_rows(args.output / "paired.csv", paired)
    save_rows(args.output / "state_uncertainty.csv", uncertainty)
    save_rows(args.output / "provider_scale.csv", scales)
    write_json(
        args.output / "report.json",
        {
            "execution": execution_provenance(),
            "competition_id": args.competition,
            "control": control_arm,
            "arms": sorted(arms),
            "matched_matches": len(ids),
            "unmatched_by_arm": {arm: len(rows) - len(ids) for arm, rows in indexed.items()},
            "slice_matches": {name: len(scopes[name]) for name in groups},
            "log_loss_intervals": intervals,
            "evidence": "retrospective development evidence; next-day xG availability is assumed",
        },
    )


def main():
    load_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("predict", "report"):
        command = commands.add_parser(name)
        command.add_argument("--competition", choices=sorted(ARMS), required=True)
        command.add_argument("--data", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--start", type=date.fromisoformat, default=date(2023, 8, 1))
        command.add_argument("--end", type=date.fromisoformat, default=date(2026, 7, 1))
    commands.choices["predict"].add_argument("--arm", required=True)
    commands.choices["report"].add_argument("--bins", type=int, default=10)
    commands.choices["report"].add_argument("--bootstrap", type=int, default=2000)
    args = parser.parse_args()
    if args.command == "predict":
        if args.arm not in ARMS[args.competition]:
            raise SystemExit(f"Unknown arm for {args.competition}: {args.arm}")
        predict(args)
    else:
        report(args)


if __name__ == "__main__":
    main()
