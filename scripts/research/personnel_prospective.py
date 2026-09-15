"""Archive and evaluate the 2026/27 starting-XI continuity experiment.

The confirmed-XI arm uses official starting XIs captured before kickoff. The expected arms
use the expected-continuity estimator at fixed horizons before kickoff. Each arm keeps the
structural M7 control and the candidate with the frozen historical coefficient.
"""

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

import numpy as np

from epl_forecast.artifacts import execution_provenance, new_run_directory
from epl_forecast.cli import save_rows
from epl_forecast.data.api_football import PLAYER_ALIASES
from epl_forecast.datasets import Dataset, timestamp
from epl_forecast.live import LONDON
from epl_forecast.models import make_model
from epl_forecast.models.quality_tilt_scores import score_diagnostics
from epl_forecast.research.personnel import (
    DEPARTED,
    MAX_UNRESOLVED,
    MEMBER,
    UNKNOWN,
    Evidence,
    candidate_shift,
    confirmed_discontinuity,
    load_evidence,
    load_propensity,
    structural_spec,
    team_confirmed,
    team_expected,
)
from epl_forecast.research.personnel_mean import shifted_scores
from epl_forecast.schema import Fixture
from epl_forecast.storage import load_environment, r2_store_if_configured, write_json
from epl_forecast.training import training_matches

COMPETITIONS = ("eng-premier-league", "eng-championship")
SEASONS = ("2025-2026", "2026-2027")
TARGET_SEASON = "2026-2027"
# Fitted once on all 8,073 oracle matches before 2026/27. Never refit on 2026/27 outcomes.
KAPPA = 0.26883582806934564
# Squads, injuries and FPL availability were all captured from this time.
SOURCES_FROM = datetime(2026, 9, 9, tzinfo=UTC)
# A fixture that kicks off from this time is prospective. Earlier fixtures are development cases.
PROSPECTIVE_FROM = datetime(2026, 9, 17, tzinfo=UTC)
HORIZONS = {"expected-24h": timedelta(hours=24), "expected-90m": timedelta(minutes=90)}
CONFIRMED = "confirmed-xi"
MAX_GOALS = 15
ALIAS_TARGETS = set(PLAYER_ALIASES.values())
R2_PREFIX = "research/evidence/personnel-measurement"


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


def starter_identity(player):
    return {
        "player_id": player,
        "identity": "API-Football lineup player ID",
        "reviewed_alias_target": int(player[1:]) in ALIAS_TARGETS,
    }


def lineup_captures(appearances, match_id, team, kickoff):
    captures = defaultdict(set)
    for row in appearances:
        if (
            row["match_id"] == match_id
            and row["team_id"] == team
            and row["starts"]
            and row["retrieved_at"] < kickoff
        ):
            captures[row["retrieved_at"]].add(row["player_id"])
    return sorted(time for time, players in captures.items() if len(players) == 11)


def previous_matches(fixtures):
    by_team = defaultdict(list)
    for row in sorted(fixtures, key=lambda item: (item["match_date"], item["match_id"])):
        if row["stage"] == "regular" and row["status"] == "finished":
            for team in (row["home_team_id"], row["away_team_id"]):
                by_team[team].append((row["match_date"], row["match_id"]))
    return by_team


def arms_for(fixture, appearances):
    kickoff = fixture["kickoff_time"]
    arms = []
    home = lineup_captures(appearances, fixture["match_id"], fixture["home_team_id"], kickoff)
    away = lineup_captures(appearances, fixture["match_id"], fixture["away_team_id"], kickoff)
    if home and away:
        arms.append((CONFIRMED, max(home[-1], away[-1])))
    for name, horizon in HORIZONS.items():
        if kickoff - horizon >= SOURCES_FROM:
            arms.append((name, kickoff - horizon))
    return arms


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
        and since <= row["kickoff_time"] < now
    ]
    history = previous_matches(fixtures)
    propensity = load_propensity()
    controls = Controls(args.data)
    records, players = [], []
    for fixture in sorted(targets, key=lambda item: (item["kickoff_time"], item["match_id"])):
        match_id, competition = fixture["match_id"], fixture["competition_id"]
        teams = {"home": fixture["home_team_id"], "away": fixture["away_team_id"]}
        previous = {
            side: [m for day, m in history[team] if day < fixture["match_date"]]
            for side, team in teams.items()
        }
        for arm, cutoff in arms_for(fixture, rows["appearances"]):
            evidence = Evidence(cutoff, **rows)
            sides = {}
            for side, team in teams.items():
                weights = evidence.recent_weights(team, previous[side])
                if arm == CONFIRMED:
                    result = team_confirmed(evidence, team, match_id, previous[side])
                    if result is not None:
                        result["starters"] = [starter_identity(p) for p in result["starters"]]
                        result["lineup_retrieved_at"] = result["lineup_retrieved_at"].isoformat()
                else:
                    result = team_expected(
                        evidence, team, match_id, competition, previous[side], propensity
                    )
                    for player in (result or {}).get("players", []):
                        players.append(
                            {"arm": arm, "match_id": match_id, "team_id": team, **player}
                        )
                sides[side] = {
                    "team_id": team,
                    "reference_matches": previous[side][-8:],
                    "recent_minutes": weights,
                    "squad_retrieved_at": None
                    if team not in evidence.squad_times
                    else evidence.squad_times[team].isoformat(),
                    **(result or {"d": None}),
                }
            shift = candidate_shift(sides["home"], sides["away"], args.kappa)
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
            records.append(
                {
                    "arm": arm,
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
                    "kappa": args.kappa,
                    "home": sides["home"],
                    "away": sides["away"],
                    "home_log_rate_shift": None if shift is None else float(shift[0]),
                    "away_log_rate_shift": None if shift is None else float(shift[1]),
                    "control": payload(scores),
                    "candidate": None if shift is None else payload(shifted_scores(scores, shift)),
                }
            )
        print(
            f"{match_id}: {len([r for r in records if r['match_id'] == match_id])} arms", flush=True
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
            "kappa": args.kappa,
            "kappa_source": "all 8,073 realized starting-XI oracle matches before 2026/27",
            "prospective_from": PROSPECTIVE_FROM.isoformat(),
            "sources_from": SOURCES_FROM.isoformat(),
            "horizons": {name: str(value) for name, value in HORIZONS.items()},
            "max_unresolved_weight": MAX_UNRESOLVED,
            "records": len(records),
            "arms": {
                arm: sum(record["arm"] == arm for record in records)
                for arm in (CONFIRMED, *HORIZONS)
            },
            "candidates": sum(record["candidate"] is not None for record in records),
            "data_manifest_batches": len(provenance["batches"]),
            "information": "Each arm uses personnel observations retrieved by its cutoff and "
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


def score(forecast, home_goals, away_goals):
    probabilities = np.array([forecast["p_home"], forecast["p_draw"], forecast["p_away"]])
    outcome = 0 if home_goals > away_goals else 1 if home_goals == away_goals else 2
    grid = forecast["score_grid"]
    cell = grid[home_goals][away_goals] if max(home_goals, away_goals) <= MAX_GOALS else 0.0
    return {
        "hda_log_loss": float(-np.log(probabilities[outcome])),
        "brier": float(np.sum((probabilities - np.eye(3)[outcome]) ** 2)),
        "score_nll": float(-np.log(cell)) if cell > 0 else None,
    }


def summary_statistics(expected, realized):
    expected, realized = np.asarray(expected, float), np.asarray(realized, float)
    if len(expected) == 0:
        return {"n": 0}
    return {
        "n": int(len(expected)),
        "bias": float(np.mean(expected - realized)),
        "mean_absolute_error": float(np.mean(np.abs(expected - realized))),
        "root_mean_square_error": float(np.sqrt(np.mean((expected - realized) ** 2))),
        "correlation": None
        if len(expected) < 3 or np.std(expected) == 0 or np.std(realized) == 0
        else float(np.corrcoef(expected, realized)[0, 1]),
        "mean_expected": float(np.mean(expected)),
        "mean_realized": float(np.mean(realized)),
    }


def evaluate_command(args):
    new_run_directory(args.output)
    records = json.loads((args.archive / "records.json").read_text())
    data = Dataset(args.data)
    try:
        fixtures = {row["match_id"]: row for row in data.fixtures()}
        appearances = data.rows(
            "SELECT match_id, team_id, player_id, starts FROM appearances "
            "WHERE season_id=? AND player_id IS NOT NULL",
            [TARGET_SEASON],
        )
    finally:
        data.close()
    starters = defaultdict(set)
    for row in appearances:
        if row["starts"]:
            starters[row["match_id"], row["team_id"]].add(row["player_id"])
    team_rows, fixture_rows, player_rows = [], [], []
    for record in records:
        fixture = fixtures.get(record["match_id"])
        if fixture is None or fixture["status"] != "finished":
            continue
        realized = {}
        for side in ("home", "away"):
            team = record[side]
            final = starters.get((record["match_id"], team["team_id"]), set())
            if team["recent_minutes"] is None or len(final) != 11:
                realized[side] = None
                continue
            realized[side] = confirmed_discontinuity(team["recent_minutes"], final)
            team_rows.append(
                {
                    "arm": record["arm"],
                    "prospective": record["prospective"],
                    "match_id": record["match_id"],
                    "competition_id": record["competition_id"],
                    "team_id": team["team_id"],
                    "side": side,
                    "d_estimate": team["d"],
                    "d_realized": realized[side],
                    "unresolved_weight": team.get("unresolved_weight"),
                    "departed_weight": sum(
                        p["recent_weight"]
                        for p in team.get("players", [])
                        if p["membership"] == DEPARTED
                    ),
                    "unknown_weight": sum(
                        p["recent_weight"]
                        for p in team.get("players", [])
                        if p["membership"] == UNKNOWN
                    ),
                    "membership_conflicts": sum(
                        bool(p["membership_conflicts"]) for p in team.get("players", [])
                    ),
                    "xi_changed_after_capture": None
                    if record["arm"] != CONFIRMED or team["d"] is None
                    else {s["player_id"] for s in team["starters"]} != final,
                }
            )
            for player in team.get("players", []):
                player_rows.append(
                    {
                        "arm": record["arm"],
                        "prospective": record["prospective"],
                        "match_id": record["match_id"],
                        "team_id": team["team_id"],
                        "player_id": player["player_id"],
                        "recent_weight": player["recent_weight"],
                        "membership": player["membership"],
                        "availability": player["availability"],
                        "start_probability": player["start_probability"],
                        "started": player["player_id"] in final,
                    }
                )
        row = {
            "arm": record["arm"],
            "prospective": record["prospective"],
            "match_id": record["match_id"],
            "competition_id": record["competition_id"],
            "home_goals": fixture["home_goals"],
            "away_goals": fixture["away_goals"],
            "d_home_estimate": record["home"]["d"],
            "d_away_estimate": record["away"]["d"],
            "d_home_realized": realized["home"],
            "d_away_realized": realized["away"],
            "home_log_rate_shift": record["home_log_rate_shift"],
        }
        for arm_name in ("control", "candidate"):
            forecast = record[arm_name]
            values = (
                {}
                if forecast is None
                else score(forecast, fixture["home_goals"], fixture["away_goals"])
            )
            for key in ("hda_log_loss", "brier", "score_nll"):
                row[f"{arm_name}_{key}"] = values.get(key)
        fixture_rows.append(row)
    summary = {"estimator": {}, "forecasts": {}, "players": {}}
    for arm in (CONFIRMED, *HORIZONS):
        for label, prospective in (("development", False), ("prospective", True)):
            teams = [
                row
                for row in team_rows
                if row["arm"] == arm
                and row["prospective"] == prospective
                and row["d_estimate"] is not None
            ]
            if not teams:
                continue
            games = [
                row
                for row in fixture_rows
                if row["arm"] == arm
                and row["prospective"] == prospective
                and None not in (row["d_home_estimate"], row["d_away_estimate"])
                and None not in (row["d_home_realized"], row["d_away_realized"])
            ]
            difference_estimate = [r["d_away_estimate"] - r["d_home_estimate"] for r in games]
            difference_realized = [r["d_away_realized"] - r["d_home_realized"] for r in games]
            pairs = list(zip(difference_estimate, difference_realized, strict=True))
            summary["estimator"][f"{arm}/{label}"] = {
                "team_d": summary_statistics(
                    [r["d_estimate"] for r in teams], [r["d_realized"] for r in teams]
                ),
                "away_minus_home_d": summary_statistics(difference_estimate, difference_realized),
                "sign_agreement_realized_at_least_0.05": _share(
                    [np.sign(e) == np.sign(r) for e, r in pairs if abs(r) >= 0.05]
                ),
                "imbalanced_realized_at_least_0.10": {
                    "fixtures": sum(abs(r) >= 0.10 for _, r in pairs),
                    "sign_agreement": _share(
                        [np.sign(e) == np.sign(r) for e, r in pairs if abs(r) >= 0.10]
                    ),
                    "mean_absolute_error": _mean([abs(e - r) for e, r in pairs if abs(r) >= 0.10]),
                },
                "false_large_estimate": sum(abs(e) >= 0.10 and abs(r) < 0.05 for e, r in pairs),
                "missed_large_realized": sum(abs(r) >= 0.10 and abs(e) < 0.05 for e, r in pairs),
                "unresolved_weight": {
                    "mean": _mean(
                        [
                            r["unresolved_weight"]
                            for r in teams
                            if r["unresolved_weight"] is not None
                        ]
                    ),
                    "maximum": max(
                        (
                            r["unresolved_weight"]
                            for r in teams
                            if r["unresolved_weight"] is not None
                        ),
                        default=None,
                    ),
                    "teams_above_limit": sum(
                        (r["unresolved_weight"] or 0) > MAX_UNRESOLVED for r in teams
                    ),
                },
                "membership_conflict_players": sum(r["membership_conflicts"] for r in teams),
                "xi_changed_after_capture": sum(bool(r["xi_changed_after_capture"]) for r in teams),
            }
            scored = [
                r
                for r in fixture_rows
                if r["arm"] == arm
                and r["prospective"] == prospective
                and r["candidate_hda_log_loss"] is not None
            ]
            summary["forecasts"][f"{arm}/{label}"] = {
                "fixtures": len(scored),
                **{
                    f"candidate_minus_control_{key}": _mean(
                        [
                            r[f"candidate_{key}"] - r[f"control_{key}"]
                            for r in scored
                            if r[f"candidate_{key}"] is not None and r[f"control_{key}"] is not None
                        ]
                    )
                    for key in ("hda_log_loss", "brier", "score_nll")
                },
            }
            members = [
                r
                for r in player_rows
                if r["arm"] == arm
                and r["prospective"] == prospective
                and r["start_probability"] is not None
            ]
            bins = defaultdict(list)
            for r in members:
                bins[min(int(r["start_probability"] * 5), 4)].append(r)
            summary["players"][f"{arm}/{label}"] = [
                {
                    "probability_bin": f"{index / 5:.1f}-{(index + 1) / 5:.1f}",
                    "players": len(values),
                    "mean_probability": _mean([v["start_probability"] for v in values]),
                    "started": _mean([v["started"] for v in values]),
                }
                for index, values in sorted(bins.items())
            ] + [
                {
                    "membership": state,
                    "players": sum(
                        r["membership"] == state
                        for r in player_rows
                        if r["arm"] == arm and r["prospective"] == prospective
                    ),
                    "started": _mean(
                        [
                            r["started"]
                            for r in player_rows
                            if r["arm"] == arm
                            and r["prospective"] == prospective
                            and r["membership"] == state
                        ]
                    ),
                }
                for state in (MEMBER, DEPARTED, UNKNOWN)
            ]
    save_rows(args.output / "teams.csv", team_rows)
    save_rows(args.output / "fixtures.csv", fixture_rows)
    save_rows(args.output / "players.csv", player_rows)
    write_json(args.output / "summary.json", summary)
    write_json(
        args.output / "manifest.json",
        {
            "execution": execution_provenance(),
            "archive": str(args.archive),
            "records": len(records),
        },
    )
    print(json.dumps(summary, indent=2))


def _mean(values):
    return None if not values else float(np.mean(values))


def _share(values):
    return {"n": len(values), "share": _mean([float(value) for value in values])}


def main():
    load_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    archive = commands.add_parser("archive")
    archive.add_argument("--data", type=Path, required=True)
    archive.add_argument("--output", type=Path, required=True)
    archive.add_argument("--since", default=SOURCES_FROM.isoformat())
    archive.add_argument("--until")
    archive.add_argument("--kappa", type=float, default=KAPPA)
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
