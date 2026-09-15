"""Archive cutoff-safe personnel mean forecasts for the next match round."""

import argparse
import copy
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from epl_forecast.artifacts import execution_provenance, new_run_directory
from epl_forecast.cli import load_config, save_rows
from epl_forecast.datasets import Dataset, timestamp
from epl_forecast.live import LONDON
from epl_forecast.models import make_model
from epl_forecast.models.quality_tilt_scores import score_diagnostics
from epl_forecast.research.availability import (
    api_probability,
    expected_discontinuity,
    fpl_probability,
    resolve_availability,
)
from epl_forecast.research.personnel_mean import (
    FULL_RECENT_MINUTES,
    WINDOW,
    lineup_minutes,
    quality_shift,
    shifted_scores,
)
from epl_forecast.schema import Fixture
from epl_forecast.storage import load_environment, write_json
from epl_forecast.training import training_matches

COMPETITIONS = ("eng-premier-league", "eng-championship")
PROSPECTIVE_KAPPA = 0.26883582806934564
MINIMUM_SQUAD = 18
MAX_GOALS = 15


def season_id(cutoff):
    year = cutoff.year - (cutoff.month < 7)
    return f"{year}-{year + 1}"


def target_fixtures(rows, cutoff, season):
    upcoming = [
        row
        for row in rows
        if row["competition_id"] in COMPETITIONS
        and row["season_id"] == season
        and row["stage"] == "regular"
        and row["status"] != "finished"
        and row["kickoff_time"] is not None
        and timestamp(row["kickoff_time"]) > cutoff
    ]
    first = {}
    for row in sorted(upcoming, key=lambda item: (item["kickoff_time"], item["match_id"])):
        for team in (row["home_team_id"], row["away_team_id"]):
            first.setdefault(team, row["match_id"])
    wanted = set(first.values())
    return [row for row in upcoming if row["match_id"] in wanted]


def current_squads(data, season):
    rows = data.rows(
        "WITH latest AS (SELECT team_id, max(retrieved_at) AS retrieved_at "
        "FROM memberships_observations WHERE provider='api_football' "
        "AND basis='captured_squad' AND season_id=? GROUP BY team_id) "
        "SELECT m.player_id, m.team_id, m.retrieved_at, m.source_sha256 "
        "FROM memberships_observations m JOIN latest l USING(team_id, retrieved_at) "
        "WHERE m.provider='api_football' AND m.basis='captured_squad' AND m.season_id=?",
        [season, season],
    )
    squads = defaultdict(dict)
    for row in rows:
        squads[row["team_id"]][row["player_id"]] = row
    return squads


def latest_api_injuries(data, season):
    rows = data.rows(
        "WITH latest AS (SELECT competition_id, max(retrieved_at) AS retrieved_at "
        "FROM availability_observations WHERE provider='api_football' "
        "AND season_id=? AND competition_id IN (?, ?) GROUP BY competition_id) "
        "SELECT a.* FROM availability_observations a "
        "JOIN latest l USING(competition_id, retrieved_at) "
        "WHERE a.provider='api_football' AND a.season_id=?",
        [season, *COMPETITIONS, season],
    )
    result = defaultdict(list)
    for row in rows:
        if row["match_id"] and row["player_id"]:
            result[row["match_id"], row["player_id"]].append(row)
    return result


def latest_fpl(data):
    rows = data.rows(
        "SELECT * FROM availability_observations WHERE provider='fpl' "
        "AND retrieved_at=(SELECT max(retrieved_at) FROM availability_observations "
        "WHERE provider='fpl')"
    )
    return {row["player_id"]: row for row in rows if row["player_id"]}


def recent_context(matches, appearances):
    recent = lineup_minutes(appearances)
    complete = {
        key: players
        for key, players in recent.items()
        if sum(players.values()) >= FULL_RECENT_MINUTES
    }
    by_team = defaultdict(list)
    for match in sorted(matches, key=lambda item: (item.fixture.match_date, item.fixture.match_id)):
        for team in (match.fixture.home_team_id, match.fixture.away_team_id):
            by_team[team].append(match)
    return complete, by_team


def recent_weights(complete, by_team, team, target_date):
    previous = [match for match in by_team[team] if match.fixture.match_date < target_date][
        -WINDOW:
    ]
    histories = [complete.get((match.fixture.match_id, team)) for match in previous]
    if len(histories) < WINDOW or any(row is None for row in histories):
        return None, previous
    weights = defaultdict(float)
    for players in histories:
        for player, minutes in players.items():
            weights[player] += minutes
    return dict(weights), previous


def evidence_for(player, match_id, competition, api_rows, fpl_rows):
    evidence = []
    for row in api_rows.get((match_id, player), []):
        evidence.append(
            {
                "provider": "api_football",
                "probability": api_probability(row),
                "status": row["status"],
                "reason": row["reason"],
                "retrieved_at": row["retrieved_at"].isoformat(),
                "source_sha256": row["source_sha256"],
            }
        )
    if competition == "eng-premier-league" and player in fpl_rows:
        row = fpl_rows[player]
        evidence.append(
            {
                "provider": "fpl",
                "probability": fpl_probability(row),
                "status": row["status"],
                "reason": row["reason"],
                "retrieved_at": row["retrieved_at"].isoformat(),
                "source_sha256": row["source_sha256"],
                "round": row["next_round"],
            }
        )
    return evidence


def team_personnel(fixture, team, weights, squad, api_rows, fpl_rows, player_names):
    if weights is None or len(squad) < MINIMUM_SQUAD:
        return None, []
    availability, rows = {}, []
    squad_time = next(iter(squad.values()))["retrieved_at"].isoformat()
    for player, weight in sorted(weights.items(), key=lambda item: item[1], reverse=True):
        evidence = evidence_for(
            player, fixture.match_id, fixture.competition_id, api_rows, fpl_rows
        )
        probability, resolution = resolve_availability(player in squad, evidence)
        availability[player] = probability
        rows.append(
            {
                "match_id": fixture.match_id,
                "team_id": team,
                "player_id": player,
                "player_name": player_names.get(player),
                "recent_minutes": weight,
                "recent_weight": weight / sum(weights.values()),
                "in_current_squad": player in squad,
                "availability_probability": probability,
                "resolution": resolution,
                "squad_retrieved_at": squad_time,
                "evidence": json.dumps(evidence, separators=(",", ":")),
            }
        )
    return expected_discontinuity(weights, availability), rows


def forecast_payload(scores):
    grid, outside = scores.grid(MAX_GOALS)
    diagnostics = score_diagnostics(scores)
    return {
        "p_home": scores.outcome_probabilities()[0],
        "p_draw": scores.outcome_probabilities()[1],
        "p_away": scores.outcome_probabilities()[2],
        "expected_home_goals": diagnostics["expected_home_goals"],
        "expected_away_goals": diagnostics["expected_away_goals"],
        "score_grid": grid.tolist(),
        "outside_grid_probability": outside,
    }


def archive(args):
    cutoff = timestamp(args.cutoff)
    season = season_id(cutoff)
    new_run_directory(args.output)
    data = Dataset(args.data, cutoff)
    try:
        fixture_rows = data.fixtures()
        matches = data.matches()
        appearances = data.player_history()
        squads = current_squads(data, season)
        api_rows = latest_api_injuries(data, season)
        fpl_rows = latest_fpl(data)
        names = {
            row["player_id"]: row["name"]
            for row in data.rows("SELECT player_id, name FROM players")
        }
        provenance = data.provenance()
    finally:
        data.close()
    targets = target_fixtures(fixture_rows, cutoff, season)
    complete, by_team = recent_context(matches, appearances)
    personnel_rows, feature_rows = [], []
    for row in targets:
        fixture = Fixture(
            row["match_id"],
            row["competition_id"],
            row["season_id"],
            row["match_date"],
            row["home_team_id"],
            row["away_team_id"],
        )
        feature = {
            "fixture": fixture,
            "kickoff_time": row["kickoff_time"].isoformat(),
        }
        for side, team in (("home", fixture.home_team_id), ("away", fixture.away_team_id)):
            weights, previous = recent_weights(complete, by_team, team, fixture.match_date)
            discontinuity, details = team_personnel(
                fixture,
                team,
                weights,
                squads.get(team, {}),
                api_rows,
                fpl_rows,
                names,
            )
            personnel_rows.extend(details)
            feature[f"d_{side}"] = discontinuity
            feature[f"{side}_reference_matches"] = [match.fixture.match_id for match in previous]
            feature[f"{side}_squad_count"] = len(squads.get(team, {}))
        feature_rows.append(feature)
    forecasts = []
    for competition in COMPETITIONS:
        config = load_config(Path("configs/product.toml"))
        config["competition_id"] = competition
        spec = copy.deepcopy(next(item for item in config["models"] if item["id"] == "M7-xg-v1"))
        spec["parameters"].update(
            competition_id=competition,
            data_root=str(args.data),
            data_cutoff=cutoff.isoformat(),
        )
        config["models"] = [spec]
        model = make_model(spec).fit(
            training_matches(matches, config, spec, cutoff.astimezone(LONDON).date()),
            as_of=cutoff.astimezone(LONDON).date(),
        )
        for feature in (
            item for item in feature_rows if item["fixture"].competition_id == competition
        ):
            fixture = feature["fixture"]
            control_scores = model.predict_match(fixture).scores
            candidate = None
            shift = None
            if feature["d_home"] is not None and feature["d_away"] is not None:
                shift = quality_shift(feature["d_home"], feature["d_away"], args.kappa)
                candidate = forecast_payload(shifted_scores(control_scores, shift))
            forecasts.append(
                {
                    "match_id": fixture.match_id,
                    "competition_id": competition,
                    "season_id": fixture.season_id,
                    "match_date": str(fixture.match_date),
                    "kickoff_time": feature["kickoff_time"],
                    "home_team_id": fixture.home_team_id,
                    "away_team_id": fixture.away_team_id,
                    "d_home": feature["d_home"],
                    "d_away": feature["d_away"],
                    "home_log_rate_shift": None if shift is None else float(shift[0]),
                    "away_log_rate_shift": None if shift is None else float(shift[1]),
                    "material": None
                    if shift is None
                    else abs(feature["d_home"] - feature["d_away"]) >= 0.10,
                    "home_reference_matches": feature["home_reference_matches"],
                    "away_reference_matches": feature["away_reference_matches"],
                    "home_squad_count": feature["home_squad_count"],
                    "away_squad_count": feature["away_squad_count"],
                    "control": forecast_payload(control_scores),
                    "candidate": candidate,
                }
            )
    save_rows(args.output / "personnel.csv", personnel_rows)
    write_json(args.output / "forecasts.json", forecasts)
    write_json(
        args.output / "manifest.json",
        {
            "execution": execution_provenance(),
            "cutoff": cutoff.isoformat(),
            "season_id": season,
            "kappa": args.kappa,
            "kappa_source": "corrected all-history oracle fit through 2025/26",
            "window": WINDOW,
            "minimum_squad": MINIMUM_SQUAD,
            "matches": len(forecasts),
            "matches_with_candidate": sum(row["candidate"] is not None for row in forecasts),
            "material_matches": sum(row["material"] is True for row in forecasts),
            "personnel_rows": len(personnel_rows),
            "data_manifest_batches": len(provenance["batches"]),
            "information": "All provider evidence was captured at or before the cutoff",
        },
    )
    print(
        json.dumps(
            {
                "matches": len(forecasts),
                "candidate": sum(row["candidate"] is not None for row in forecasts),
                "material": sum(row["material"] is True for row in forecasts),
            }
        )
    )


def main():
    load_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cutoff", type=datetime.fromisoformat, required=True)
    parser.add_argument("--kappa", type=float, default=PROSPECTIVE_KAPPA)
    args = parser.parse_args()
    archive(args)


if __name__ == "__main__":
    main()
