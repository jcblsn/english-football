"""Archive and evaluate one expected-personnel forecast at fixed horizons before kickoff.

Each snapshot runs the same estimator at its cutoff. It keeps the structural M7 control and a
candidate for each personnel representation, the starting XI and the matchday squad, with
coefficients frozen from the historical oracle. The horizons are evaluation checkpoints, not
product variants. Official lineups are outcome labels only.
"""

import argparse
import csv
import importlib.util
import json
from collections import defaultdict
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

import numpy as np

from epl_forecast.artifacts import execution_provenance, new_run_directory
from epl_forecast.cli import save_rows
from epl_forecast.datasets import Dataset, timestamp
from epl_forecast.live import LONDON
from epl_forecast.models import make_model
from epl_forecast.models.quality_tilt_scores import score_diagnostics
from epl_forecast.research.personnel import (
    DEPARTED,
    MAX_UNRESOLVED,
    MEMBER,
    REPRESENTATIONS,
    UNKNOWN,
    Evidence,
    candidate_shift,
    load_evidence,
    load_propensity,
    realized_discontinuity,
    structural_spec,
    team_expected,
)
from epl_forecast.research.personnel_mean import quality_shift, shifted_scores
from epl_forecast.schema import Fixture
from epl_forecast.storage import load_environment, r2_store_if_configured, write_json
from epl_forecast.training import training_matches

_spec = importlib.util.spec_from_file_location(
    "personnel_mean_script", Path(__file__).with_name("personnel_mean.py")
)
pm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pm)

COMPETITIONS = ("eng-premier-league", "eng-championship")
SEASONS = ("2025-2026", "2026-2027")
TARGET_SEASON = "2026-2027"
# Fitted once on all 8,073 oracle matches before 2026/27. Never refit on 2026/27 outcomes.
KAPPA = {"xi": 0.26883582806934564, "squad": 0.43161578781583126}
# Squads, injuries and FPL availability were all captured from this time.
SOURCES_FROM = datetime(2026, 9, 9, tzinfo=UTC)
# A fixture that kicks off from this time is prospective. Earlier fixtures are development cases.
PROSPECTIVE_FROM = datetime(2026, 9, 17, tzinfo=UTC)
HORIZONS = {
    "6d": timedelta(days=6),
    "3d": timedelta(days=3),
    "24h": timedelta(hours=24),
    "90m": timedelta(minutes=90),
}
MAX_GOALS = 15
R2_PREFIX = "research/evidence/personnel-measurement"
METRICS = ("hda_log_loss", "brier", "score_nll")


def payload(scores):
    grid, outside = scores.grid(MAX_GOALS)
    probabilities = scores.outcome_probabilities()
    diagnostics = score_diagnostics(scores)
    return {
        "p_home": float(probabilities[0]),
        "p_draw": float(probabilities[1]),
        "p_away": float(probabilities[2]),
        "expected_home_goals": float(diagnostics["expected_home_goals"]),
        "expected_away_goals": float(diagnostics["expected_away_goals"]),
        "score_grid": np.asarray(grid).tolist(),
        "outside_grid_probability": float(outside),
    }


def previous_matches(fixtures):
    by_team = defaultdict(list)
    for row in sorted(fixtures, key=lambda item: (item["match_date"], item["match_id"])):
        if row["stage"] == "regular" and row["status"] == "finished":
            for team in (row["home_team_id"], row["away_team_id"]):
                by_team[team].append((row["match_date"], row["match_id"]))
    return by_team


class Controls:
    """One structural M7 fit for each competition and London day, from data before that day."""

    def __init__(self, root):
        self.root, self.models, self.matches = root, {}, {}

    def get(self, competition, day):
        key = competition, day
        if key not in self.models:
            cutoff = datetime.combine(day, time(), tzinfo=LONDON).astimezone(UTC)
            if day not in self.matches:
                data = Dataset(self.root, cutoff)
                try:
                    self.matches[day] = data.matches()
                finally:
                    data.close()
            config, spec = structural_spec(competition, self.root, cutoff)
            model = make_model(spec).fit(
                training_matches(self.matches[day], config, spec, day), as_of=day
            )
            self.models[key] = model, cutoff
        return self.models[key]


def archive_command(args):
    now = datetime.now(UTC) if args.until is None else timestamp(args.until)
    since = timestamp(args.since)
    new_run_directory(args.output)
    data = Dataset(args.data)
    try:
        fixtures = data.fixtures()
        rows = load_evidence(data, SEASONS)
        provenance = data.provenance()
    finally:
        data.close()
    targets = [
        row
        for row in fixtures
        if row["competition_id"] in COMPETITIONS
        and row["season_id"] == TARGET_SEASON
        and row["stage"] == "regular"
        and row["kickoff_time"] is not None
        and since <= row["kickoff_time"]
        and row["kickoff_time"] - min(HORIZONS.values()) < now
    ]
    history = previous_matches(fixtures)
    propensity = load_propensity()
    controls = Controls(args.data)
    records, players = [], []
    for fixture in sorted(targets, key=lambda item: (item["kickoff_time"], item["match_id"])):
        match_id, competition = fixture["match_id"], fixture["competition_id"]
        teams = {"home": fixture["home_team_id"], "away": fixture["away_team_id"]}
        for horizon, offset in HORIZONS.items():
            cutoff = fixture["kickoff_time"] - offset
            if cutoff < SOURCES_FROM or cutoff > now:
                continue
            evidence = Evidence(cutoff, **rows)
            sides = {}
            for side, team in teams.items():
                previous = [m for day, m in history[team] if day < fixture["match_date"]]
                estimate = team_expected(
                    evidence, team, match_id, competition, previous, propensity
                )
                for player in (estimate or {}).get("players", []):
                    players.append(
                        {
                            "horizon": horizon,
                            "match_id": match_id,
                            "team_id": team,
                            **{
                                k: v
                                for k, v in player.items()
                                if k not in ("probability", "availability", "selection")
                            },
                            **{
                                f"probability_{r}": player["probability"].get(r)
                                for r in REPRESENTATIONS
                            },
                            **{
                                f"availability_{r}": player["availability"].get(r)
                                for r in REPRESENTATIONS
                            },
                            **{f"selection_{r}": player["selection"][r] for r in REPRESENTATIONS},
                        }
                    )
                sides[side] = {
                    "team_id": team,
                    "reference_matches": previous[-8:],
                    "recent_minutes": evidence.recent_weights(team, previous),
                    "squad_retrieved_at": None
                    if team not in evidence.squad_times
                    else evidence.squad_times[team].isoformat(),
                    **{r: None if estimate is None else estimate[r] for r in REPRESENTATIONS},
                }
            model, information_cutoff = controls.get(competition, cutoff.astimezone(LONDON).date())
            scores = model.predict_match(
                Fixture(
                    match_id,
                    competition,
                    fixture["season_id"],
                    fixture["match_date"],
                    teams["home"],
                    teams["away"],
                )
            ).scores
            candidates = {}
            for representation in REPRESENTATIONS:
                shift = candidate_shift(
                    sides["home"][representation],
                    sides["away"][representation],
                    KAPPA[representation],
                )
                candidates[representation] = {
                    "kappa": KAPPA[representation],
                    "home_log_rate_shift": None if shift is None else float(shift[0]),
                    "forecast": None if shift is None else payload(shifted_scores(scores, shift)),
                }
            records.append(
                {
                    "horizon": horizon,
                    "match_id": match_id,
                    "competition_id": competition,
                    "season_id": fixture["season_id"],
                    "match_date": str(fixture["match_date"]),
                    "kickoff_time": fixture["kickoff_time"].isoformat(),
                    "prospective": fixture["kickoff_time"] >= PROSPECTIVE_FROM,
                    "personnel_cutoff": cutoff.isoformat(),
                    "m7_information_cutoff": information_cutoff.isoformat(),
                    "injuries_retrieved_at": {
                        key: value.isoformat() for key, value in evidence.injury_times.items()
                    },
                    "fpl_retrieved_at": None
                    if evidence.fpl_time is None
                    else evidence.fpl_time.isoformat(),
                    "home": sides["home"],
                    "away": sides["away"],
                    "control": payload(scores),
                    "control_score_parameters": pm.score_parameters(scores),
                    "candidates": candidates,
                }
            )
        print(
            f"{match_id}: {sum(r['match_id'] == match_id for r in records)} snapshots", flush=True
        )
    write_json(args.output / "records.json", records)
    save_rows(args.output / "players.csv", players)
    write_json(
        args.output / "manifest.json",
        {
            "execution": execution_provenance(),
            "archived_at": datetime.now(UTC).isoformat(),
            "since": since.isoformat(),
            "until": now.isoformat(),
            "kappa": KAPPA,
            "kappa_source": "all 8,073 realized oracle matches before 2026/27, one fit each",
            "prospective_from": PROSPECTIVE_FROM.isoformat(),
            "sources_from": SOURCES_FROM.isoformat(),
            "horizons": {name: str(value) for name, value in HORIZONS.items()},
            "max_unresolved_weight": MAX_UNRESOLVED,
            "records": len(records),
            "snapshots": {h: sum(r["horizon"] == h for r in records) for h in HORIZONS},
            "candidates": {
                r: sum(record["candidates"][r]["forecast"] is not None for record in records)
                for r in REPRESENTATIONS
            },
            "data_manifest_batches": len(provenance["batches"]),
            "information": "Each snapshot uses personnel observations retrieved by its cutoff and "
            "an M7 fit from data retrieved before the London day of the cutoff",
        },
    )
    if args.upload:
        store = r2_store_if_configured("R2_DATA_BUCKET")
        commit = execution_provenance()["commit"][:7]
        for path in sorted(args.output.rglob("*")):
            if path.is_file():
                key = f"{R2_PREFIX}/{commit}/{args.output.name}/{path.relative_to(args.output)}"
                store.upload(path, key, immutable=True)
        print(f"Uploaded to {R2_PREFIX}/{commit}/{args.output.name}")


def score_payload(forecast, home_goals, away_goals):
    probabilities = np.array([forecast["p_home"], forecast["p_draw"], forecast["p_away"]])
    outcome = 0 if home_goals > away_goals else 1 if home_goals == away_goals else 2
    cell = (
        forecast["score_grid"][home_goals][away_goals]
        if max(home_goals, away_goals) <= MAX_GOALS
        else 0.0
    )
    return {
        "hda_log_loss": float(-np.log(probabilities[outcome])),
        "brier": float(np.sum((probabilities - np.eye(3)[outcome]) ** 2)),
        "score_nll": float(-np.log(cell)) if cell > 0 else None,
    }


def _mean(values):
    values = [value for value in values if value is not None]
    return None if not values else float(np.mean(values))


def statistics(estimates, labels):
    estimates, labels = np.asarray(estimates, float), np.asarray(labels, float)
    if len(estimates) == 0:
        return {"n": 0}
    return {
        "n": int(len(estimates)),
        "mean_estimate": float(np.mean(estimates)),
        "mean_realized": float(np.mean(labels)),
        "bias": float(np.mean(estimates - labels)),
        "mean_absolute_error": float(np.mean(np.abs(estimates - labels))),
        "root_mean_square_error": float(np.sqrt(np.mean((estimates - labels) ** 2))),
        "correlation": None
        if len(estimates) < 3 or np.std(estimates) == 0 or np.std(labels) == 0
        else float(np.corrcoef(estimates, labels)[0, 1]),
    }


def evaluate_command(args):
    new_run_directory(args.output)
    records = json.loads((args.archive / "records.json").read_text())
    players = {}
    for row in csv.DictReader((args.archive / "players.csv").open()):
        players.setdefault((row["horizon"], row["match_id"], row["team_id"]), []).append(row)
    data = Dataset(args.data)
    try:
        fixtures = data.fixtures()
        rows = load_evidence(data, SEASONS)
    finally:
        data.close()
    by_id = {row["match_id"]: row for row in fixtures}
    history = previous_matches(fixtures)
    final = Evidence(datetime.now(UTC) + timedelta(days=3650), **rows)
    labels = {}
    for match_id in {record["match_id"] for record in records}:
        fixture = by_id[match_id]
        if fixture["status"] != "finished":
            continue
        for team in (fixture["home_team_id"], fixture["away_team_id"]):
            previous = [m for day, m in history[team] if day < fixture["match_date"]]
            weights = final.recent_weights(team, previous)
            starters = final.started.get((match_id, team), set())
            matchday = final.matchday.get((match_id, team), set())
            if weights is None or len(starters) != 11:
                continue
            labels[match_id, team] = {
                "xi": realized_discontinuity(weights, starters),
                "squad": realized_discontinuity(weights, matchday),
                "starters": starters,
                "matchday": matchday,
            }
    team_rows, fixture_rows, player_rows = [], [], []
    for record in records:
        fixture = by_id[record["match_id"]]
        if (record["match_id"], record["home"]["team_id"]) not in labels or (
            record["match_id"],
            record["away"]["team_id"],
        ) not in labels:
            continue
        label = {
            side: labels[record["match_id"], record[side]["team_id"]] for side in ("home", "away")
        }
        control_scores = pm.scores_from_parameters(record["control_score_parameters"])
        base = {
            "horizon": record["horizon"],
            "prospective": record["prospective"],
            "match_id": record["match_id"],
            "competition_id": record["competition_id"],
        }
        for side in ("home", "away"):
            for representation in REPRESENTATIONS:
                estimate = record[side][representation]
                team_rows.append(
                    {
                        **base,
                        "team_id": record[side]["team_id"],
                        "representation": representation,
                        "estimate": None if estimate is None else estimate["d"],
                        "unresolved_weight": None
                        if estimate is None
                        else estimate["unresolved_weight"],
                        "realized": label[side][representation],
                    }
                )
            for player in players.get(
                (record["horizon"], record["match_id"], record[side]["team_id"]), []
            ):
                player_rows.append(
                    {
                        **base,
                        "team_id": record[side]["team_id"],
                        "player_id": player["player_id"],
                        "membership": player["membership"],
                        "conflict": player["membership_conflicts"] not in ("", "[]"),
                        "probability_xi": None
                        if player["probability_xi"] in ("", "None")
                        else float(player["probability_xi"]),
                        "probability_squad": None
                        if player["probability_squad"] in ("", "None")
                        else float(player["probability_squad"]),
                        "started": player["player_id"] in label[side]["starters"],
                        "in_squad": player["player_id"] in label[side]["matchday"],
                    }
                )
        control = score_payload(record["control"], fixture["home_goals"], fixture["away_goals"])
        for representation in REPRESENTATIONS:
            home, away = record["home"][representation], record["away"][representation]
            candidate = record["candidates"][representation]
            realized_difference = label["away"][representation] - label["home"][representation]
            oracle_shift = quality_shift(
                label["home"][representation], label["away"][representation], KAPPA[representation]
            )
            oracle = pm.individual_scores(
                {
                    **fixture,
                    "outcome": "HDA"[
                        0
                        if fixture["home_goals"] > fixture["away_goals"]
                        else 1
                        if fixture["home_goals"] == fixture["away_goals"]
                        else 2
                    ],
                },
                shifted_scores(control_scores, oracle_shift),
            )
            row = {
                **base,
                "representation": representation,
                "home_goals": fixture["home_goals"],
                "away_goals": fixture["away_goals"],
                "estimated_difference": None
                if home is None or away is None or home["d"] is None or away["d"] is None
                else away["d"] - home["d"],
                "realized_difference": realized_difference,
                "candidate": candidate["forecast"] is not None,
                **{f"control_{m}": control[m] for m in METRICS},
                **{f"oracle_{m}": oracle[m] for m in METRICS},
            }
            values = (
                {}
                if candidate["forecast"] is None
                else score_payload(
                    candidate["forecast"], fixture["home_goals"], fixture["away_goals"]
                )
            )
            row.update({f"candidate_{m}": values.get(m) for m in METRICS})
            fixture_rows.append(row)

    estimates = defaultdict(dict)
    for row in team_rows:
        if row["estimate"] is not None:
            estimates[row["match_id"], row["team_id"], row["representation"]][row["horizon"]] = row[
                "estimate"
            ]
    order = list(HORIZONS)
    complete = {
        (match_id, representation)
        for (match_id, _, representation), values in estimates.items()
        if len(values) == len(order)
    }
    summary = {"estimator": {}, "revisions": {}, "forecasts": {}, "players": {}}
    for label_name, prospective in (("development", False), ("prospective", True)):
        for representation in REPRESENTATIONS:
            for horizon in order:
                key = f"{label_name}/{representation}/{horizon}"
                teams = [
                    r
                    for r in team_rows
                    if r["prospective"] == prospective
                    and r["representation"] == representation
                    and r["horizon"] == horizon
                    and r["estimate"] is not None
                ]
                if not teams:
                    continue
                games = [
                    r
                    for r in fixture_rows
                    if r["prospective"] == prospective
                    and r["representation"] == representation
                    and r["horizon"] == horizon
                    and r["estimated_difference"] is not None
                ]
                pairs = [(r["estimated_difference"], r["realized_difference"]) for r in games]
                summary["estimator"][key] = {
                    "team_d": statistics(
                        [r["estimate"] for r in teams], [r["realized"] for r in teams]
                    ),
                    "away_minus_home_d": statistics([e for e, _ in pairs], [r for _, r in pairs]),
                    "sign_agreement_realized_at_least_0.05": [
                        sum(np.sign(e) == np.sign(r) for e, r in pairs if abs(r) >= 0.05),
                        sum(abs(r) >= 0.05 for _, r in pairs),
                    ],
                    "sign_agreement_realized_at_least_0.10": [
                        sum(np.sign(e) == np.sign(r) for e, r in pairs if abs(r) >= 0.10),
                        sum(abs(r) >= 0.10 for _, r in pairs),
                    ],
                    "false_large_estimate": sum(abs(e) >= 0.10 and abs(r) < 0.05 for e, r in pairs),
                    "missed_large_realized": sum(
                        abs(r) >= 0.10 and abs(e) < 0.05 for e, r in pairs
                    ),
                    "mean_unresolved_weight": _mean([r["unresolved_weight"] for r in teams]),
                    "teams_above_unresolved_limit": sum(
                        (r["unresolved_weight"] or 0) > MAX_UNRESOLVED for r in teams
                    ),
                    "matched_fixtures_all_horizons": statistics(
                        [
                            e
                            for (e, _), g in zip(pairs, games, strict=True)
                            if (g["match_id"], representation) in complete
                        ],
                        [
                            r
                            for (_, r), g in zip(pairs, games, strict=True)
                            if (g["match_id"], representation) in complete
                        ],
                    ),
                }
                scored = [r for r in games if r["candidate"]]
                summary["forecasts"][key] = {
                    "fixtures": len(scored),
                    **{
                        f"candidate_minus_control_{m}": _mean(
                            [
                                None
                                if r[f"candidate_{m}"] is None or r[f"control_{m}"] is None
                                else r[f"candidate_{m}"] - r[f"control_{m}"]
                                for r in scored
                            ]
                        )
                        for m in METRICS
                    },
                    **{
                        f"oracle_minus_control_{m}": _mean(
                            [
                                None
                                if r[f"oracle_{m}"] is None or r[f"control_{m}"] is None
                                else r[f"oracle_{m}"] - r[f"control_{m}"]
                                for r in scored
                            ]
                        )
                        for m in METRICS
                    },
                }
                chosen = [
                    r
                    for r in player_rows
                    if r["prospective"] == prospective
                    and r["horizon"] == horizon
                    and r[f"probability_{representation}"] is not None
                ]
                outcome = "started" if representation == "xi" else "in_squad"
                bins = defaultdict(list)
                for r in chosen:
                    bins[min(int(r[f"probability_{representation}"] * 5), 4)].append(r)
                summary["players"][key] = {
                    "calibration": [
                        {
                            "bin": f"{i / 5:.1f}-{(i + 1) / 5:.1f}",
                            "players": len(v),
                            "mean_probability": _mean(
                                [x[f"probability_{representation}"] for x in v]
                            ),
                            "observed": _mean([float(x[outcome]) for x in v]),
                        }
                        for i, v in sorted(bins.items())
                    ],
                    "membership": {
                        state: {
                            "players": sum(
                                r["membership"] == state
                                for r in player_rows
                                if r["prospective"] == prospective and r["horizon"] == horizon
                            ),
                            "started": _mean(
                                [
                                    float(r["started"])
                                    for r in player_rows
                                    if r["prospective"] == prospective
                                    and r["horizon"] == horizon
                                    and r["membership"] == state
                                ]
                            ),
                            "in_squad": _mean(
                                [
                                    float(r["in_squad"])
                                    for r in player_rows
                                    if r["prospective"] == prospective
                                    and r["horizon"] == horizon
                                    and r["membership"] == state
                                ]
                            ),
                        }
                        for state in (MEMBER, DEPARTED, UNKNOWN)
                    },
                    "membership_conflicts": sum(
                        r["conflict"]
                        for r in player_rows
                        if r["prospective"] == prospective and r["horizon"] == horizon
                    ),
                }
            revisions = {}
            for earlier, later in zip(order, order[1:], strict=False):
                changes = [
                    abs(values[later] - values[earlier])
                    for (match_id, team, r), values in estimates.items()
                    if r == representation
                    and earlier in values
                    and later in values
                    and next(x["prospective"] for x in records if x["match_id"] == match_id)
                    == prospective
                ]
                revisions[f"{earlier}->{later}"] = {
                    "teams": len(changes),
                    "mean_absolute_change": _mean(changes),
                }
            summary["revisions"][f"{label_name}/{representation}"] = revisions
    save_rows(args.output / "teams.csv", team_rows)
    save_rows(args.output / "fixtures.csv", fixture_rows)
    save_rows(args.output / "players.csv", player_rows)
    summary = json.loads(json.dumps(summary, default=lambda value: value.item()))
    write_json(args.output / "summary.json", summary)
    write_json(
        args.output / "manifest.json",
        {
            "execution": execution_provenance(),
            "archive": str(args.archive),
            "records": len(records),
            "labels": "final starting XI and matchday squad, with the eight matches before the target",
            "oracle": "the same frozen coefficient applied to the realized label; mechanism check only",
        },
    )
    print(json.dumps(summary, indent=1))


def main():
    load_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    archive = commands.add_parser("archive")
    archive.add_argument("--data", type=Path, required=True)
    archive.add_argument("--output", type=Path, required=True)
    archive.add_argument("--since", default=SOURCES_FROM.isoformat())
    archive.add_argument("--until")
    archive.add_argument("--upload", action="store_true")
    archive.set_defaults(func=archive_command)
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--data", type=Path, required=True)
    evaluate.add_argument("--archive", type=Path, required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    evaluate.set_defaults(func=evaluate_command)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
