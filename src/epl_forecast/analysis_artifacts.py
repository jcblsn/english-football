"""Normalize indexed publication artifacts into the DuckDB analysis schema."""

import json
import math
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor

from epl_forecast.analysis_keys import HINDCAST_INDEX_KEY, MATCH_HINDCAST_INDEX_KEY
from epl_forecast.competitions import COMPETITION_IDS
from epl_forecast.personnel import team_unusable_reason

ARTIFACT_TABLES = (
    "forecasts",
    "forecast_matches",
    "forecast_match_stages",
    "forecast_score_distributions",
    "forecast_score_grid",
    "forecast_personnel_teams",
    "forecast_personnel_players",
    "forecast_personnel_evidence",
    "forecast_personnel_reference_matches",
    "forecast_market_inputs",
    "forecast_teams",
    "forecast_team_events",
    "forecast_points_distribution",
    "forecast_position_distribution",
    "forecast_intervals",
    "model_team_states",
    "forecast_runs",
    "model_specifications",
    "forecast_simulation_runs",
    "forecast_simulation_teams",
    "forecast_simulation_team_events",
    "forecast_simulation_points_distribution",
    "forecast_simulation_position_distribution",
    "forecast_simulation_goal_difference_distribution",
    "forecast_simulation_intervals",
    "forecast_simulation_europe_probabilities",
    "forecast_simulation_match_frequencies",
    "forecast_impact_fixtures",
    "forecast_impacts",
    "hindcast_origins",
    "hindcast_teams",
    "hindcast_team_events",
    "hindcast_points_distribution",
    "hindcast_position_distribution",
    "hindcast_intervals",
    "hindcast_simulation_runs",
    "hindcast_simulation_teams",
    "hindcast_simulation_team_events",
    "hindcast_simulation_points_distribution",
    "hindcast_simulation_position_distribution",
    "hindcast_simulation_goal_difference_distribution",
    "hindcast_simulation_intervals",
    "hindcast_simulation_europe_probabilities",
    "hindcast_simulation_match_frequencies",
    "match_hindcasts",
    "match_hindcast_score_grid",
    "record_matches",
    "record_summary",
)


def _json(value) -> str | None:
    return None if value is None else json.dumps(value, sort_keys=True, allow_nan=False)


def _create_table(
    connection,
    name: str,
    columns: tuple[tuple[str, str], ...],
    rows=(),
    *,
    create=True,
) -> None:
    if create:
        connection.execute(
            f"CREATE TABLE IF NOT EXISTS analysis.{name} ("
            + ", ".join(f'"{column}" {kind}' for column, kind in columns)
            + ")"
        )
    if not rows:
        return
    names = [column for column, _ in columns]
    json_columns = {column for column, kind in columns if kind == "JSON"}
    schema = json.dumps(
        [
            {
                row[1]: row[2]
                for row in connection.execute(f"PRAGMA table_info('analysis.{name}')").fetchall()
            }
        ]
    )
    for start in range(0, len(rows), 10_000):
        payload = []
        for row in rows[start : start + 10_000]:
            values = {column: row.get(column) for column in names}
            for column in json_columns:
                if isinstance(values[column], str):
                    values[column] = json.loads(values[column])
            payload.append(values)
        connection.execute(
            f"INSERT INTO analysis.{name} BY NAME "
            "SELECT unnest(from_json_strict(?, ?), recursive := true)",
            [json.dumps(payload, allow_nan=False), schema],
        )


def _document(store, key: str, version: int | tuple[int, ...], kind: str) -> dict:
    document = store.get_json(key)
    if document is None:
        raise ValueError(f"The {kind} pointer does not resolve: {key}")
    versions = (version,) if isinstance(version, int) else version
    if document.get("schema_version") not in versions:
        raise ValueError(f"Unsupported {kind} schema at {key}: {document.get('schema_version')!r}")
    return document


def _required(document: dict, fields: Iterable[str], kind: str) -> None:
    missing = sorted(set(fields) - set(document))
    if missing:
        raise ValueError(f"Missing {kind} fields: {', '.join(missing)}")


def _team_rows(product_id: str, team: dict, base: dict, targets: dict[str, list]) -> None:
    scalar = {
        **base,
        "team_id": team["team_id"],
        "team_name": team.get("name"),
        "played": team.get("played"),
        "current_points": team.get("current_points"),
        "mean_points": team.get("mean_points"),
        "median_points": team.get("median_points"),
        "mean_position": team.get("mean_position"),
        "median_position": team.get("median_position"),
        "position_sd": team.get("position_sd"),
        "mean_goal_difference": team.get("mean_goal_difference"),
    }
    targets[product_id + "_teams"].append(scalar)
    for event, probability in team.get("events", {}).items():
        targets[product_id + "_team_events"].append(
            {**base, "team_id": team["team_id"], "event": event, "probability": probability}
        )
    for points, probability in team.get("points_distribution", {}).items():
        targets[product_id + "_points_distribution"].append(
            {
                **base,
                "team_id": team["team_id"],
                "points": int(points),
                "probability": probability,
            }
        )
    for position, probability in enumerate(team.get("position_probabilities", ()), 1):
        targets[product_id + "_position_distribution"].append(
            {
                **base,
                "team_id": team["team_id"],
                "position": position,
                "probability": probability,
            }
        )
    for kind in ("points", "position"):
        for level, bounds in team.get(f"{kind}_intervals", {}).items():
            targets[product_id + "_intervals"].append(
                {
                    **base,
                    "team_id": team["team_id"],
                    "estimate": kind,
                    "level": int(level),
                    "lower": bounds[0],
                    "upper": bounds[1],
                }
            )


STAGES = (
    ("unadjusted", 1, "model_state"),
    ("personnel_adjusted", 2, "unadjusted"),
    ("market_assisted", 3, "personnel_adjusted"),
)


def _probability_stages(match: dict, schema_version: int) -> dict[str, dict | None]:
    if schema_version >= 2:
        return match["stages"]
    personnel = match.get("personnel") or {}
    shift = personnel.get("home_log_rate_shift")
    adjusted = {
        "p_home": match.get("p_home"),
        "p_draw": match.get("p_draw"),
        "p_away": match.get("p_away"),
        "score_distribution": match.get("score_distribution"),
    }
    unadjusted = (
        None if shift is not None and shift != 0 else {**adjusted, "historical_identity": True}
    )
    return {
        "unadjusted": unadjusted,
        "personnel_adjusted": adjusted,
        "market_assisted": match.get("market_assisted_probabilities"),
    }


def _match_detail_rows(
    match: dict,
    base: dict,
    schema_version: int,
    on_public_surface: bool,
    targets: dict[str, list],
) -> None:
    identity = {**base, "match_id": match["match_id"]}
    personnel = match.get("personnel") or {}
    shift = personnel.get("home_log_rate_shift")
    stages = _probability_stages(match, schema_version)
    for stage, order, parent in STAGES:
        value = stages.get(stage)
        score = (value or {}).get("score_distribution")
        if value is not None:
            reason = None
        elif stage == "unadjusted" and schema_version == 1 and shift not in (None, 0):
            reason = "The historical artifact retained only the post-personnel distribution."
        elif stage == "market_assisted":
            reason = "No usable market quote was available."
        else:
            reason = "The artifact does not contain this stage."
        targets["forecast_match_stages"].append(
            {
                **identity,
                "stage": stage,
                "stage_order": order,
                "parent_stage": parent,
                "available": value is not None,
                "availability_reason": reason,
                "p_home": None if value is None else value.get("p_home"),
                "p_draw": None if value is None else value.get("p_draw"),
                "p_away": None if value is None else value.get("p_away"),
                "home_rate": None if score is None else score.get("home_rate"),
                "away_rate": None if score is None else score.get("away_rate"),
                "personnel_shift_available": shift is not None,
                "personnel_applied": shift is not None and shift != 0,
                "home_log_rate_shift": shift,
                "market_family": None if value is None else value.get("market_family"),
                "market_observed_at": None if value is None else value.get("market_observed_at"),
                "market_weight": None if value is None else value.get("market_weight"),
                "on_public_surface": on_public_surface,
            }
        )
        if score is None:
            continue
        grid = score.get("grid_home_rows_away_columns") or []
        targets["forecast_score_distributions"].append(
            {
                **identity,
                "stage": stage,
                "home_rate": score.get("home_rate"),
                "away_rate": score.get("away_rate"),
                "omitted_probability": score.get("omitted_probability"),
                "uncertainty_components": _json(score.get("uncertainty_components")),
                "home_goal_values": len(grid),
                "away_goal_values": max((len(row) for row in grid), default=0),
            }
        )
        for home_goals, row in enumerate(grid):
            for away_goals, probability in enumerate(row):
                targets["forecast_score_grid"].append(
                    {
                        **identity,
                        "stage": stage,
                        "home_goals": home_goals,
                        "away_goals": away_goals,
                        "probability": probability,
                    }
                )
    market = stages.get("market_assisted")
    if market is not None:
        odds = market.get("decimal_odds") or {}
        probabilities = market.get("market_probabilities") or {}
        targets["forecast_market_inputs"].append(
            {
                **identity,
                "market_family": market.get("market_family"),
                "market_observed_at": market.get("market_observed_at"),
                "home_odds": odds.get("home"),
                "draw_odds": odds.get("draw"),
                "away_odds": odds.get("away"),
                "market_p_home": probabilities.get("p_home"),
                "market_p_draw": probabilities.get("p_draw"),
                "market_p_away": probabilities.get("p_away"),
                "raw_implied_probability_sum": market.get("raw_implied_probability_sum"),
                "market_weight": market.get("market_weight"),
            }
        )


def _personnel_rows(match: dict, base: dict, kappa, targets: dict[str, list]) -> None:
    record = match.get("personnel")
    if not record:
        return
    identity = {**base, "match_id": match["match_id"]}
    shift = record.get("home_log_rate_shift")
    applied = shift is not None and shift != 0
    reasons = {side: team_unusable_reason(record.get(side) or {}) for side in ("home", "away")}
    for side in ("home", "away"):
        team = record.get(side) or {}
        team_id = match[f"{side}_team_id"]
        unresolved = team.get("unresolved_weight")
        usable = reasons[side] is None
        other = reasons["away" if side == "home" else "home"]
        if shift is not None:
            status = "applied" if applied else "neutral"
        elif not usable:
            status = reasons[side]
        elif other is not None:
            status = "other_team_unusable"
        else:
            status = "shift_unavailable"
        targets["forecast_personnel_teams"].append(
            {
                **identity,
                "side": side,
                "team_id": team_id,
                "discontinuity": team.get("discontinuity"),
                "unresolved_weight": unresolved,
                "team_sheet_retrieved_at": team.get("team_sheet_retrieved_at"),
                "usable_for_shift": usable,
                "kappa": kappa,
                "home_log_rate_shift": shift,
                "team_log_rate_shift": None
                if shift is None
                else shift
                if side == "home"
                else -shift,
                "personnel_applied": applied,
                "status": status,
            }
        )
        for reference in team.get("reference_matches", ()):
            match_id = reference.get("match_id") if isinstance(reference, dict) else reference
            targets["forecast_personnel_reference_matches"].append(
                {
                    **identity,
                    "team_id": team_id,
                    "side": side,
                    "reference_match_id": match_id,
                    "reference": _json(reference) if isinstance(reference, dict) else None,
                }
            )
        for player in team.get("players", ()):
            probability = player.get("probability")
            recent_weight = player.get("recent_weight")
            expected = (
                None
                if probability is None or recent_weight is None
                else recent_weight * (1 - probability)
            )
            contribution = (
                None
                if expected is None or unresolved is None or unresolved >= 1
                else expected / (1 - unresolved)
            )
            player_base = {
                **identity,
                "team_id": team_id,
                "side": side,
                "player_id": player["player_id"],
            }
            targets["forecast_personnel_players"].append(
                {
                    **player_base,
                    "player_name": player.get("player_name"),
                    "recent_weight": recent_weight,
                    "membership": player.get("membership"),
                    "recent_squads": player.get("recent_squads"),
                    "in_last_squad": player.get("in_last_squad"),
                    "availability": player.get("availability"),
                    "selection_probability": probability,
                    "membership_basis": _json(player.get("membership_basis")),
                    "membership_conflicts": _json(player.get("membership_conflicts")),
                    "availability_basis": _json(player.get("availability_basis")),
                    "expected_missing_weight": expected,
                    "discontinuity_contribution": contribution,
                }
            )
            for evidence_kind in (
                "membership_basis",
                "membership_conflicts",
                "availability_basis",
            ):
                for ordinal, evidence in enumerate(player.get(evidence_kind) or (), 1):
                    targets["forecast_personnel_evidence"].append(
                        {
                            **player_base,
                            "evidence_kind": evidence_kind,
                            "ordinal": ordinal,
                            "basis": _json(evidence),
                        }
                    )


def _simulation_rows(
    simulation: dict,
    base: dict,
    targets: dict[str, list],
    prefix: str = "forecast",
    team_names: dict | None = None,
) -> None:
    team_names = team_names or {}
    targets[f"{prefix}_simulation_runs"].append(
        {
            **base,
            "simulations": simulation.get("simulations"),
            "seed": simulation.get("seed"),
            "as_of": simulation.get("as_of"),
            "results_observed_at": simulation.get("results_observed_at"),
            "played_matches": simulation.get("played_matches"),
            "remaining_matches": simulation.get("remaining_matches"),
            "state_uncertainty": simulation.get("state_uncertainty"),
            "future_state_evolution": simulation.get("future_state_evolution"),
            "head_to_head_applied_rate": simulation.get("head_to_head_applied_rate"),
            "unresolved_decisive_tie_rate": simulation.get("unresolved_decisive_tie_rate"),
            "ranking_rules": _json(simulation.get("ranking_rules")),
            "ranking_diagnostics": _json(simulation.get("ranking_rules_evidence")),
            "tie_diagnostics": _json(
                {
                    "disciplinary_tiebreaks_available": simulation.get(
                        "disciplinary_tiebreaks_available"
                    ),
                    "head_to_head_applied_rate": simulation.get("head_to_head_applied_rate"),
                    "unresolved_decisive_tie_rate": simulation.get("unresolved_decisive_tie_rate"),
                }
            ),
            "point_adjustments": _json(simulation.get("point_adjustments")),
            "assumptions": _json(simulation.get("assumptions")),
            "playoff_model": _json(simulation.get("playoff_model")),
            "europe_scenario": _json(simulation.get("europe_scenario")),
        }
    )
    for team in simulation.get("teams", ()):
        team_base = {**base, "team_id": team["team_id"]}
        targets[f"{prefix}_simulation_teams"].append(
            {
                **team_base,
                **{column: team.get(column) for column, _ in TEAM_COLUMNS if column != "team_name"},
                "team_name": team.get("name") or team_names.get(team["team_id"]),
            }
        )
        for key, value in team.items():
            if key.endswith("_probability") and isinstance(value, (int, float)):
                targets[f"{prefix}_simulation_team_events"].append(
                    {**team_base, "event": key, "probability": value}
                )
        for points, probability in team.get("points_distribution", {}).items():
            targets[f"{prefix}_simulation_points_distribution"].append(
                {**team_base, "points": int(points), "probability": probability}
            )
        for position, probability in enumerate(team.get("position_probabilities", ()), 1):
            targets[f"{prefix}_simulation_position_distribution"].append(
                {**team_base, "position": position, "probability": probability}
            )
        for difference, probability in team.get("goal_difference_distribution", {}).items():
            targets[f"{prefix}_simulation_goal_difference_distribution"].append(
                {**team_base, "goal_difference": int(difference), "probability": probability}
            )
        for estimate in ("points", "position"):
            for level, bounds in team.get(f"{estimate}_intervals", {}).items():
                targets[f"{prefix}_simulation_intervals"].append(
                    {
                        **team_base,
                        "estimate": estimate,
                        "level": int(level),
                        "lower": bounds[0],
                        "upper": bounds[1],
                    }
                )
        for scenario, probability in team.get("conditional_europe_probabilities", {}).items():
            targets[f"{prefix}_simulation_europe_probabilities"].append(
                {**team_base, "scenario": scenario, "probability": probability}
            )
    frequencies = simulation.get("match_frequencies") or {}
    if isinstance(frequencies, dict):
        iterator = frequencies.items()
    else:
        iterator = ((row.get("match_id"), row) for row in frequencies)
    for match_id, value in iterator:
        if isinstance(value, dict):
            home = value.get("p_home", value.get("home", value.get("home_win")))
            draw = value.get("p_draw", value.get("draw"))
            away = value.get("p_away", value.get("away", value.get("away_win")))
        else:
            home, draw, away = value
        targets[f"{prefix}_simulation_match_frequencies"].append(
            {
                **base,
                "match_id": match_id,
                "p_home": home,
                "p_draw": draw,
                "p_away": away,
            }
        )


def _live_rows(
    data_store,
    publish_store,
) -> tuple[dict[str, list], dict, set[str]]:
    rows = {
        name: []
        for name in (
            "forecasts",
            "forecast_matches",
            "forecast_match_stages",
            "forecast_score_distributions",
            "forecast_score_grid",
            "forecast_personnel_teams",
            "forecast_personnel_players",
            "forecast_personnel_evidence",
            "forecast_personnel_reference_matches",
            "forecast_market_inputs",
            "forecast_teams",
            "forecast_team_events",
            "forecast_points_distribution",
            "forecast_position_distribution",
            "forecast_intervals",
            "model_team_states",
            "forecast_runs",
            "model_specifications",
            "forecast_simulation_runs",
            "forecast_simulation_teams",
            "forecast_simulation_team_events",
            "forecast_simulation_points_distribution",
            "forecast_simulation_position_distribution",
            "forecast_simulation_goal_difference_distribution",
            "forecast_simulation_intervals",
            "forecast_simulation_europe_probabilities",
            "forecast_simulation_match_frequencies",
            "forecast_impact_fixtures",
            "forecast_impacts",
        )
    }
    updated = {}
    model_versions = set()
    for competition_id in COMPETITION_IDS:
        key = f"forecasts/{competition_id}/archive.json"
        archive = publish_store.get_json(key)
        if archive is None:
            continue
        if archive.get("schema_version") != 1:
            raise ValueError(
                f"Unsupported forecast archive schema at {key}: {archive.get('schema_version')!r}"
            )
        _required(archive, ("forecasts", "updated_at", "competition_id"), "forecast archive")
        if archive["competition_id"] != competition_id:
            raise ValueError(f"Forecast archive competition does not match its key: {key}")
        updated[key] = archive["updated_at"]
        for pointer in archive["forecasts"]:
            _required(pointer, ("forecast_id", "href"), "forecast pointer")
            forecast_id = pointer["forecast_id"]
            public = _document(publish_store, pointer["href"], 3, "forecast")
            _required(
                public,
                (
                    "forecast_id",
                    "competition_id",
                    "season_id",
                    "generated_at",
                    "state_observed_at",
                    "model_results_cutoff",
                    "simulations",
                    "model",
                    "matches",
                    "teams",
                ),
                "forecast",
            )
            if public["forecast_id"] != pointer["forecast_id"]:
                raise ValueError(f"Forecast pointer identity does not match: {pointer['href']}")
            forecast_id = public["forecast_id"]
            private_prefix = f"runs/forecasts/{forecast_id}/{competition_id}"
            private = _document(
                data_store, f"{private_prefix}/forecast.json", (1, 2), "private forecast"
            )
            run = data_store.get_json(f"{private_prefix}/run.json")
            if run is None:
                raise ValueError(
                    f"A successful public forecast has no private run: {private_prefix}"
                )
            if (
                private.get("competition_id") != competition_id
                or private.get("season_id") != public["season_id"]
            ):
                raise ValueError(f"Private and public forecast identities differ: {forecast_id}")
            public_matches = {match["match_id"] for match in public["matches"]}
            private_matches = {match["match_id"] for match in private.get("matches", ())}
            if not public_matches <= private_matches:
                raise ValueError(
                    f"Public forecast has matches absent from its private run: {forecast_id}"
                )
            model_version = public["model"]["version"]
            model_versions.add(model_version)
            base = {
                "forecast_id": forecast_id,
                "competition_id": competition_id,
                "season_id": public["season_id"],
            }
            rows["forecasts"].append(
                {
                    **base,
                    "generated_at": public["generated_at"],
                    "state_observed_at": public["state_observed_at"],
                    "model_results_cutoff": public["model_results_cutoff"],
                    "public_model_version": model_version,
                    "private_model_id": private.get("model", {}).get("id"),
                    "private_schema_version": private["schema_version"],
                    "simulations": public["simulations"],
                    "public_href": pointer["href"],
                    "private_prefix": private_prefix,
                }
            )
            private_schema = private["schema_version"]
            personnel_summary = private.get("personnel") or {}
            for match in private.get("matches", ()):
                assisted = match.get("market_assisted_probabilities")
                on_public_surface = match["match_id"] in public_matches
                rows["forecast_matches"].append(
                    {
                        **base,
                        "match_id": match["match_id"],
                        "kickoff_time": match.get("kickoff_time"),
                        "match_date": match.get("match_date"),
                        "home_team_id": match["home_team_id"],
                        "away_team_id": match["away_team_id"],
                        "status": match.get("status"),
                        "on_public_surface": on_public_surface,
                        "structural_p_home": match.get("p_home"),
                        "structural_p_draw": match.get("p_draw"),
                        "structural_p_away": match.get("p_away"),
                        "market_assisted_p_home": None
                        if assisted is None
                        else assisted.get("p_home"),
                        "market_assisted_p_draw": None
                        if assisted is None
                        else assisted.get("p_draw"),
                        "market_assisted_p_away": None
                        if assisted is None
                        else assisted.get("p_away"),
                        "market_family": None
                        if assisted is None
                        else assisted.get("market_family"),
                        "market_observed_at": None
                        if assisted is None
                        else assisted.get("market_observed_at"),
                        "personnel": _json(match.get("personnel")),
                    }
                )
                _match_detail_rows(match, base, private_schema, on_public_surface, rows)
                _personnel_rows(match, base, personnel_summary.get("kappa"), rows)
            simulation = private.get("simulation") or {}
            _simulation_rows(simulation, base, rows, team_names=private.get("team_names"))
            for team in simulation.get("teams", ()):
                public_team = next(
                    (row for row in public["teams"] if row["team_id"] == team["team_id"]), team
                )
                _team_rows("forecast", public_team, base, rows)
            for state in private.get("team_strengths", ()):
                rows["model_team_states"].append(
                    {
                        **base,
                        "team_id": state["team_id"],
                        "quality": state.get("quality"),
                        "tilt": state.get("tilt"),
                        "quality_sd": state.get("quality_sd"),
                        "tilt_sd": state.get("tilt_sd"),
                        "quality_tilt_covariance": state.get("quality_tilt_covariance"),
                        "quality_level": state.get("quality_level"),
                        "quality_form": state.get("quality_form"),
                        "quality_level_sd": state.get("quality_level_sd"),
                        "quality_form_sd": state.get("quality_form_sd"),
                        "quality_level_form_covariance": state.get("quality_level_form_covariance"),
                        "attack_log_rate": state.get("attack_log_rate"),
                        "defense_log_rate": state.get("defense_log_rate"),
                        "attack_sd": state.get("attack_sd"),
                        "defense_sd": state.get("defense_sd"),
                        "attack_multiplier": state.get("attack_multiplier"),
                        "defense_multiplier": state.get("defense_multiplier"),
                        "training_matches": state.get("training_matches"),
                        "state_source": state.get("state_source"),
                        "season_matches": state.get("season_matches"),
                        "state": _json(state),
                    }
                )
            rows["forecast_runs"].append(
                {
                    **base,
                    "generated_at": public["generated_at"],
                    "model_id": private.get("model", {}).get("id"),
                    "model_version": model_version,
                    "package_version": run.get("package_version"),
                    "code_sha256": run.get("code_sha256"),
                    "commit": run.get("execution", {}).get("commit"),
                    "training_matches": private.get("training_matches"),
                    "training_date_max": private.get("training_date_max"),
                    "league_away_goal_rate": private.get("league_away_goal_rate"),
                    "league_log_rate": math.log(private["league_away_goal_rate"])
                    if private.get("league_away_goal_rate", 0) > 0
                    else None,
                    "home_scoring_multiplier": private.get("home_scoring_multiplier"),
                    "home_advantage_log": math.log(private["home_scoring_multiplier"])
                    if private.get("home_scoring_multiplier", 0) > 0
                    else None,
                    "state_uncertainty": private.get("state_uncertainty"),
                    "future_state_evolution": private.get("future_state_evolution"),
                    "personnel_kappa": personnel_summary.get("kappa"),
                    "personnel_horizon_days": personnel_summary.get("horizon_days"),
                    "personnel_records": personnel_summary.get("records"),
                    "personnel_adjusted_fixtures": personnel_summary.get("adjusted_fixtures"),
                    "persistent_state_changed": personnel_summary.get("persistent_state_changed"),
                    "market_available_match_forecasts": (
                        private.get("market_assistance") or {}
                    ).get("available_match_forecasts"),
                    "season_simulation_uses_market": (private.get("market_assistance") or {}).get(
                        "season_simulation_uses_market"
                    ),
                    "fit_diagnostics": _json(private.get("fit_diagnostics")),
                    "provenance": _json(run),
                }
            )
            for index, specification in enumerate(
                (private.get("fit_diagnostics") or {}).get("specifications", ())
            ):
                rows["model_specifications"].append(
                    {
                        **base,
                        "specification_index": index,
                        "quality_retention": specification.get("quality_retention"),
                        "quality_sd": specification.get("quality_sd"),
                        "form_retention": specification.get("form_retention"),
                        "form_sd": specification.get("form_sd"),
                        "tilt_retention": specification.get("tilt_retention"),
                        "tilt_sd": specification.get("tilt_sd"),
                        "dispersion": specification.get("dispersion"),
                        "chance_probability": specification.get("chance_probability"),
                        "prior_weight": specification.get("prior_weight"),
                        "posterior_weight": specification.get("posterior_weight"),
                        "log_evidence": specification.get("log_evidence"),
                    }
                )
            impact = public.get("impact") or {}
            event_baselines = {
                team["team_id"]: team.get("events", {}) for team in public.get("teams", ())
            }
            for fixture in impact.get("fixtures", ()):
                carried = fixture.get("carried_from") or {}
                counts = fixture.get("outcome_counts") or {}
                rows["forecast_impact_fixtures"].append(
                    {
                        **base,
                        "match_id": fixture["match_id"],
                        "match_date": fixture.get("match_date"),
                        "kickoff_time": fixture.get("kickoff_time"),
                        "home_team_id": fixture.get("home_team_id"),
                        "away_team_id": fixture.get("away_team_id"),
                        "status": fixture.get("status"),
                        "outcome": fixture.get("outcome"),
                        "outcome_count_home": counts.get("home"),
                        "outcome_count_draw": counts.get("draw"),
                        "outcome_count_away": counts.get("away"),
                        "sufficient_sample": fixture.get("sufficient_sample"),
                        "max_standard_error": fixture.get("max_standard_error"),
                        "top_rms_movement": fixture.get("top_rms_movement"),
                        "unavailable_reason": fixture.get("unavailable_reason"),
                        "carried_from_forecast_id": carried.get("forecast_id"),
                        "carried_from_generated_at": carried.get("generated_at"),
                        "impact_horizon_days": impact.get("horizon_days"),
                        "impact_window_start": impact.get("window_start"),
                        "impact_window_end": impact.get("window_end"),
                        "impact_coverage": impact.get("coverage"),
                        "minimum_conditional_samples": impact.get("minimum_conditional_samples"),
                    }
                )
                for event, block in fixture.get("impacts", {}).items():
                    for index, team_id in enumerate(block.get("team_id", ())):
                        for outcome in ("home", "draw", "away"):
                            values = block.get(outcome, ())
                            baselines = block.get("baseline", ())
                            movements = block.get("rms_movement", ())
                            rows["forecast_impacts"].append(
                                {
                                    **base,
                                    "match_id": fixture["match_id"],
                                    "event": event,
                                    "team_id": team_id,
                                    "outcome": outcome,
                                    "baseline": baselines[index]
                                    if index < len(baselines)
                                    else event_baselines.get(team_id, {}).get(event),
                                    "conditional_probability": values[index]
                                    if index < len(values)
                                    else None,
                                    "rms_movement": movements[index]
                                    if index < len(movements)
                                    else None,
                                    "carried_from_forecast_id": carried.get("forecast_id"),
                                    "carried_from_generated_at": carried.get("generated_at"),
                                }
                            )
    return rows, updated, model_versions


def _hindcast_rows(
    data_store,
    publish_store,
    model_versions: frozenset | None = None,
) -> tuple[dict[str, list], dict, set[str]]:
    names = (
        "hindcast_origins",
        "hindcast_teams",
        "hindcast_team_events",
        "hindcast_points_distribution",
        "hindcast_position_distribution",
        "hindcast_intervals",
        "hindcast_simulation_runs",
        "hindcast_simulation_teams",
        "hindcast_simulation_team_events",
        "hindcast_simulation_points_distribution",
        "hindcast_simulation_position_distribution",
        "hindcast_simulation_goal_difference_distribution",
        "hindcast_simulation_intervals",
        "hindcast_simulation_europe_probabilities",
        "hindcast_simulation_match_frequencies",
    )
    rows = {name: [] for name in names}
    index = publish_store.get_json(HINDCAST_INDEX_KEY)
    if index is None:
        return rows, {}, set()
    if index.get("schema_version") != 1 or index.get("retrospective") is not True:
        raise ValueError("Unsupported or non-retrospective hindcast index")
    _required(index, ("updated_at", "seasons"), "hindcast index")
    versions = set()
    origins = []
    for pointer in index["seasons"]:
        _required(pointer, ("href", "model_version"), "hindcast index season")
        if model_versions is not None and pointer["model_version"] not in model_versions:
            continue
        series = _document(publish_store, pointer["href"], 1, "hindcast series")
        if series.get("retrospective") is not True:
            raise ValueError(f"Hindcast series is not retrospective: {pointer['href']}")
        origins.extend(series["origins"])

    def load(origin):
        public = _document(publish_store, origin["href"], 1, "hindcast")
        if public.get("retrospective") is not True:
            raise ValueError(f"Hindcast origin is not retrospective: {origin['href']}")
        private_key = f"runs/{origin['href']}"
        private = data_store.get_json(private_key)
        if private is None:
            raise ValueError(f"The private hindcast pointer does not resolve: {private_key}")
        _required(
            private,
            ("hindcast_id", "competition_id", "season_id", "origin_at", "simulation"),
            "private hindcast",
        )
        if private.get("hindcast_id") != public.get("hindcast_id"):
            raise ValueError(f"Private and public hindcast identities differ: {origin['href']}")
        base = {
            "hindcast_id": public["hindcast_id"],
            "competition_id": public["competition_id"],
            "season_id": public["season_id"],
            "model_version": public["model"]["version"],
            "origin_at": public["origin_at"],
        }
        artifact_rows = {name: [] for name in names}
        artifact_rows["hindcast_origins"].append(
            {
                **base,
                "retrospective": True,
                "generated_at": None,
                "model_results_cutoff": public["model_results_cutoff"],
                "simulations": public["simulations"],
                "played_matches": public.get("played_matches"),
                "remaining_matches": public.get("remaining_matches"),
                "public_href": origin["href"],
                "private_key": private_key,
            }
        )
        for team in public["teams"]:
            _team_rows("hindcast", team, base, artifact_rows)
        _simulation_rows(
            private["simulation"],
            base,
            artifact_rows,
            "hindcast",
            {team["team_id"]: team.get("name") for team in public["teams"]},
        )
        return public["model"]["version"], artifact_rows

    with ThreadPoolExecutor(max_workers=16) as pool:
        documents = list(pool.map(load, origins))
    for model_version, artifact_rows in documents:
        versions.add(model_version)
        for table, values in artifact_rows.items():
            rows[table].extend(values)
    return rows, {HINDCAST_INDEX_KEY: index["updated_at"]}, versions


MATCH_HINDCAST_IDENTITY = ("model_version", "competition_id", "season_id", "match_id")


def _match_hindcast_rows(
    publish_store, model_versions: frozenset | None = None
) -> tuple[dict[str, list], dict, set[str]]:
    """Retrospective match forecasts, from the season documents the match-hindcast index selects."""
    rows = {"match_hindcasts": [], "match_hindcast_score_grid": []}
    index = publish_store.get_json(MATCH_HINDCAST_INDEX_KEY)
    if index is None:
        return rows, {}, set()
    if index.get("schema_version") != 1 or index.get("retrospective") is not True:
        raise ValueError("Unsupported or non-retrospective match-hindcast index")
    _required(index, ("updated_at", "seasons"), "match-hindcast index")
    selected = []
    for pointer in index["seasons"]:
        _required(pointer, ("href", "model_version"), "match-hindcast index season")
        if model_versions is None or pointer["model_version"] in model_versions:
            selected.append(pointer)
    with ThreadPoolExecutor(max_workers=16) as pool:
        documents = list(
            pool.map(
                lambda pointer: _document(publish_store, pointer["href"], 1, "match hindcast"),
                selected,
            )
        )
    versions = set()
    for pointer, document in zip(selected, documents, strict=True):
        if document.get("retrospective") is not True:
            raise ValueError(f"Match hindcast is not retrospective: {pointer['href']}")
        _required(
            document,
            ("competition_id", "season_id", "model", "prospective_from", "matches"),
            "match hindcast",
        )
        model_version = document["model"]["version"]
        versions.add(model_version)
        base = {
            "model_version": model_version,
            "competition_id": document["competition_id"],
            "season_id": document["season_id"],
        }
        for match in document["matches"]:
            personnel = match.get("personnel") or {}
            scores = match.get("score_probabilities") or {}
            unadjusted = match.get("unadjusted") or {}
            rows["match_hindcasts"].append(
                {
                    **base,
                    "match_id": match["match_id"],
                    "retrospective": True,
                    "match_date": match["match_date"],
                    "kickoff_time": match.get("kickoff_time"),
                    "home_team_id": match["home_team_id"],
                    "away_team_id": match["away_team_id"],
                    "origin_at": match["origin_at"],
                    "model_results_cutoff": match["model_results_cutoff"],
                    "prospective_from": document["prospective_from"],
                    "p_home": match["p_home"],
                    "p_draw": match["p_draw"],
                    "p_away": match["p_away"],
                    "unadjusted_p_home": unadjusted.get("p_home"),
                    "unadjusted_p_draw": unadjusted.get("p_draw"),
                    "unadjusted_p_away": unadjusted.get("p_away"),
                    "personnel_applied": personnel.get("home_log_rate_shift") is not None,
                    "home_discontinuity": personnel.get("home_discontinuity"),
                    "away_discontinuity": personnel.get("away_discontinuity"),
                    "home_log_rate_shift": personnel.get("home_log_rate_shift"),
                    "home_rate": scores.get("home_rate"),
                    "away_rate": scores.get("away_rate"),
                    "omitted_probability": scores.get("omitted_probability"),
                    "public_href": pointer["href"],
                }
            )
            for home_goals, line in enumerate(scores.get("grid_home_rows_away_columns", ())):
                for away_goals, probability in enumerate(line):
                    rows["match_hindcast_score_grid"].append(
                        {
                            **base,
                            "match_id": match["match_id"],
                            "home_goals": home_goals,
                            "away_goals": away_goals,
                            "probability": probability,
                        }
                    )
    return rows, {MATCH_HINDCAST_INDEX_KEY: index["updated_at"]}, versions


def _record_rows(publish_store) -> tuple[list[dict], list[dict], dict]:
    record = publish_store.get_json("record.json")
    if record is None:
        return [], [], {}
    if record.get("schema_version") != 2:
        raise ValueError(f"Unsupported prospective record schema: {record.get('schema_version')!r}")
    matches = []
    for state in ("pending", "settled"):
        for row in record.get(state, ()):
            matches.append(
                {
                    "record_state": state,
                    "match_id": row["match_id"],
                    "competition_id": row.get("competition_id"),
                    "season_id": row.get("season_id"),
                    "forecast_id": row["forecast_id"],
                    "generated_at": row.get("generated_at"),
                    "kickoff_time": row.get("kickoff_time"),
                    "model_version": row.get("model_version"),
                    "p_home": row.get("p_home"),
                    "p_draw": row.get("p_draw"),
                    "p_away": row.get("p_away"),
                    "outcome": row.get("outcome"),
                }
            )
    summaries = []
    for scope, value in record.get("summary", {}).items():
        if not isinstance(value, dict):
            continue
        summaries.append(
            {
                "scope": scope,
                "scored": value.get("scored"),
                "log_loss": value.get("log_loss"),
                "brier": value.get("brier"),
                "classwise_ece": value.get("classwise_ece"),
                "metrics": _json(value),
            }
        )
    return matches, summaries, {"record.json": record.get("updated_at")}


TEAM_COLUMNS = (
    ("team_id", "VARCHAR"),
    ("team_name", "VARCHAR"),
    ("played", "INTEGER"),
    ("current_points", "INTEGER"),
    ("mean_points", "DOUBLE"),
    ("median_points", "DOUBLE"),
    ("mean_position", "DOUBLE"),
    ("median_position", "DOUBLE"),
    ("position_sd", "DOUBLE"),
    ("mean_goal_difference", "DOUBLE"),
)


def _install_live(connection, rows: dict[str, list]) -> None:
    base = (("forecast_id", "VARCHAR"), ("competition_id", "VARCHAR"), ("season_id", "VARCHAR"))
    _create_table(
        connection,
        "forecasts",
        base
        + (
            ("generated_at", "TIMESTAMPTZ"),
            ("state_observed_at", "TIMESTAMPTZ"),
            ("model_results_cutoff", "DATE"),
            ("public_model_version", "VARCHAR"),
            ("private_model_id", "VARCHAR"),
            ("private_schema_version", "INTEGER"),
            ("simulations", "INTEGER"),
            ("public_href", "VARCHAR"),
            ("private_prefix", "VARCHAR"),
        ),
        rows["forecasts"],
    )
    _create_table(
        connection,
        "forecast_matches",
        base
        + (
            ("match_id", "VARCHAR"),
            ("kickoff_time", "TIMESTAMPTZ"),
            ("match_date", "DATE"),
            ("home_team_id", "VARCHAR"),
            ("away_team_id", "VARCHAR"),
            ("status", "VARCHAR"),
            ("on_public_surface", "BOOLEAN"),
            ("structural_p_home", "DOUBLE"),
            ("structural_p_draw", "DOUBLE"),
            ("structural_p_away", "DOUBLE"),
            ("market_assisted_p_home", "DOUBLE"),
            ("market_assisted_p_draw", "DOUBLE"),
            ("market_assisted_p_away", "DOUBLE"),
            ("market_family", "VARCHAR"),
            ("market_observed_at", "TIMESTAMPTZ"),
            ("personnel", "JSON"),
        ),
        rows["forecast_matches"],
    )
    _create_table(
        connection,
        "forecast_match_stages",
        base
        + (
            ("match_id", "VARCHAR"),
            ("stage", "VARCHAR"),
            ("stage_order", "INTEGER"),
            ("parent_stage", "VARCHAR"),
            ("available", "BOOLEAN"),
            ("availability_reason", "VARCHAR"),
            ("p_home", "DOUBLE"),
            ("p_draw", "DOUBLE"),
            ("p_away", "DOUBLE"),
            ("home_rate", "DOUBLE"),
            ("away_rate", "DOUBLE"),
            ("personnel_shift_available", "BOOLEAN"),
            ("personnel_applied", "BOOLEAN"),
            ("home_log_rate_shift", "DOUBLE"),
            ("market_family", "VARCHAR"),
            ("market_observed_at", "TIMESTAMPTZ"),
            ("market_weight", "DOUBLE"),
            ("on_public_surface", "BOOLEAN"),
        ),
        rows["forecast_match_stages"],
    )
    _create_table(
        connection,
        "forecast_score_distributions",
        base
        + (
            ("match_id", "VARCHAR"),
            ("stage", "VARCHAR"),
            ("home_rate", "DOUBLE"),
            ("away_rate", "DOUBLE"),
            ("omitted_probability", "DOUBLE"),
            ("uncertainty_components", "JSON"),
            ("home_goal_values", "INTEGER"),
            ("away_goal_values", "INTEGER"),
        ),
        rows["forecast_score_distributions"],
    )
    _create_table(
        connection,
        "forecast_score_grid",
        base
        + (
            ("match_id", "VARCHAR"),
            ("stage", "VARCHAR"),
            ("home_goals", "INTEGER"),
            ("away_goals", "INTEGER"),
            ("probability", "DOUBLE"),
        ),
        rows["forecast_score_grid"],
    )
    _create_table(
        connection,
        "forecast_personnel_teams",
        base
        + (
            ("match_id", "VARCHAR"),
            ("side", "VARCHAR"),
            ("team_id", "VARCHAR"),
            ("discontinuity", "DOUBLE"),
            ("unresolved_weight", "DOUBLE"),
            ("team_sheet_retrieved_at", "TIMESTAMPTZ"),
            ("usable_for_shift", "BOOLEAN"),
            ("kappa", "DOUBLE"),
            ("home_log_rate_shift", "DOUBLE"),
            ("team_log_rate_shift", "DOUBLE"),
            ("personnel_applied", "BOOLEAN"),
            ("status", "VARCHAR"),
        ),
        rows["forecast_personnel_teams"],
    )
    _create_table(
        connection,
        "forecast_personnel_players",
        base
        + (
            ("match_id", "VARCHAR"),
            ("team_id", "VARCHAR"),
            ("side", "VARCHAR"),
            ("player_id", "VARCHAR"),
            ("player_name", "VARCHAR"),
            ("recent_weight", "DOUBLE"),
            ("membership", "VARCHAR"),
            ("recent_squads", "INTEGER"),
            ("in_last_squad", "BOOLEAN"),
            ("availability", "VARCHAR"),
            ("selection_probability", "DOUBLE"),
            ("membership_basis", "JSON"),
            ("membership_conflicts", "JSON"),
            ("availability_basis", "JSON"),
            ("expected_missing_weight", "DOUBLE"),
            ("discontinuity_contribution", "DOUBLE"),
        ),
        rows["forecast_personnel_players"],
    )
    _create_table(
        connection,
        "forecast_personnel_evidence",
        base
        + (
            ("match_id", "VARCHAR"),
            ("team_id", "VARCHAR"),
            ("side", "VARCHAR"),
            ("player_id", "VARCHAR"),
            ("evidence_kind", "VARCHAR"),
            ("ordinal", "INTEGER"),
            ("basis", "JSON"),
        ),
        rows["forecast_personnel_evidence"],
    )
    _create_table(
        connection,
        "forecast_personnel_reference_matches",
        base
        + (
            ("match_id", "VARCHAR"),
            ("team_id", "VARCHAR"),
            ("side", "VARCHAR"),
            ("reference_match_id", "VARCHAR"),
            ("reference", "JSON"),
        ),
        rows["forecast_personnel_reference_matches"],
    )
    _create_table(
        connection,
        "forecast_market_inputs",
        base
        + (
            ("match_id", "VARCHAR"),
            ("market_family", "VARCHAR"),
            ("market_observed_at", "TIMESTAMPTZ"),
            ("home_odds", "DOUBLE"),
            ("draw_odds", "DOUBLE"),
            ("away_odds", "DOUBLE"),
            ("market_p_home", "DOUBLE"),
            ("market_p_draw", "DOUBLE"),
            ("market_p_away", "DOUBLE"),
            ("raw_implied_probability_sum", "DOUBLE"),
            ("market_weight", "DOUBLE"),
        ),
        rows["forecast_market_inputs"],
    )
    _create_table(connection, "forecast_teams", base + TEAM_COLUMNS, rows["forecast_teams"])
    _create_table(
        connection,
        "forecast_team_events",
        base + (("team_id", "VARCHAR"), ("event", "VARCHAR"), ("probability", "DOUBLE")),
        rows["forecast_team_events"],
    )
    _create_table(
        connection,
        "forecast_points_distribution",
        base + (("team_id", "VARCHAR"), ("points", "INTEGER"), ("probability", "DOUBLE")),
        rows["forecast_points_distribution"],
    )
    _create_table(
        connection,
        "forecast_position_distribution",
        base + (("team_id", "VARCHAR"), ("position", "INTEGER"), ("probability", "DOUBLE")),
        rows["forecast_position_distribution"],
    )
    _create_table(
        connection,
        "forecast_intervals",
        base
        + (
            ("team_id", "VARCHAR"),
            ("estimate", "VARCHAR"),
            ("level", "INTEGER"),
            ("lower", "DOUBLE"),
            ("upper", "DOUBLE"),
        ),
        rows["forecast_intervals"],
    )
    _create_table(
        connection,
        "model_team_states",
        base
        + (
            ("team_id", "VARCHAR"),
            ("quality", "DOUBLE"),
            ("tilt", "DOUBLE"),
            ("quality_sd", "DOUBLE"),
            ("tilt_sd", "DOUBLE"),
            ("quality_tilt_covariance", "DOUBLE"),
            ("quality_level", "DOUBLE"),
            ("quality_form", "DOUBLE"),
            ("quality_level_sd", "DOUBLE"),
            ("quality_form_sd", "DOUBLE"),
            ("quality_level_form_covariance", "DOUBLE"),
            ("attack_log_rate", "DOUBLE"),
            ("defense_log_rate", "DOUBLE"),
            ("attack_sd", "DOUBLE"),
            ("defense_sd", "DOUBLE"),
            ("attack_multiplier", "DOUBLE"),
            ("defense_multiplier", "DOUBLE"),
            ("training_matches", "INTEGER"),
            ("state_source", "VARCHAR"),
            ("season_matches", "INTEGER"),
            ("state", "JSON"),
        ),
        rows["model_team_states"],
    )
    _create_table(
        connection,
        "forecast_runs",
        base
        + (
            ("generated_at", "TIMESTAMPTZ"),
            ("model_id", "VARCHAR"),
            ("model_version", "VARCHAR"),
            ("package_version", "VARCHAR"),
            ("code_sha256", "VARCHAR"),
            ("commit", "VARCHAR"),
            ("training_matches", "INTEGER"),
            ("training_date_max", "DATE"),
            ("league_away_goal_rate", "DOUBLE"),
            ("league_log_rate", "DOUBLE"),
            ("home_scoring_multiplier", "DOUBLE"),
            ("home_advantage_log", "DOUBLE"),
            ("state_uncertainty", "VARCHAR"),
            ("future_state_evolution", "BOOLEAN"),
            ("personnel_kappa", "DOUBLE"),
            ("personnel_horizon_days", "INTEGER"),
            ("personnel_records", "INTEGER"),
            ("personnel_adjusted_fixtures", "INTEGER"),
            ("persistent_state_changed", "BOOLEAN"),
            ("market_available_match_forecasts", "INTEGER"),
            ("season_simulation_uses_market", "BOOLEAN"),
            ("fit_diagnostics", "JSON"),
            ("provenance", "JSON"),
        ),
        rows["forecast_runs"],
    )
    _create_table(
        connection,
        "model_specifications",
        base
        + (
            ("specification_index", "INTEGER"),
            ("quality_retention", "DOUBLE"),
            ("quality_sd", "DOUBLE"),
            ("form_retention", "DOUBLE"),
            ("form_sd", "DOUBLE"),
            ("tilt_retention", "DOUBLE"),
            ("tilt_sd", "DOUBLE"),
            ("dispersion", "DOUBLE"),
            ("chance_probability", "DOUBLE"),
            ("prior_weight", "DOUBLE"),
            ("posterior_weight", "DOUBLE"),
            ("log_evidence", "DOUBLE"),
        ),
        rows["model_specifications"],
    )
    _create_table(
        connection,
        "forecast_simulation_runs",
        base
        + (
            ("simulations", "INTEGER"),
            ("seed", "BIGINT"),
            ("as_of", "DATE"),
            ("results_observed_at", "TIMESTAMPTZ"),
            ("played_matches", "INTEGER"),
            ("remaining_matches", "INTEGER"),
            ("state_uncertainty", "VARCHAR"),
            ("future_state_evolution", "BOOLEAN"),
            ("head_to_head_applied_rate", "DOUBLE"),
            ("unresolved_decisive_tie_rate", "DOUBLE"),
            ("ranking_rules", "JSON"),
            ("ranking_diagnostics", "JSON"),
            ("tie_diagnostics", "JSON"),
            ("point_adjustments", "JSON"),
            ("assumptions", "JSON"),
            ("playoff_model", "JSON"),
            ("europe_scenario", "JSON"),
        ),
        rows["forecast_simulation_runs"],
    )
    _create_table(
        connection,
        "forecast_simulation_teams",
        base + TEAM_COLUMNS,
        rows["forecast_simulation_teams"],
    )
    for suffix, value_column in (
        ("team_events", (("event", "VARCHAR"),)),
        ("points_distribution", (("points", "INTEGER"),)),
        ("position_distribution", (("position", "INTEGER"),)),
        ("goal_difference_distribution", (("goal_difference", "INTEGER"),)),
        ("europe_probabilities", (("scenario", "VARCHAR"),)),
    ):
        _create_table(
            connection,
            f"forecast_simulation_{suffix}",
            base + (("team_id", "VARCHAR"),) + value_column + (("probability", "DOUBLE"),),
            rows[f"forecast_simulation_{suffix}"],
        )
    _create_table(
        connection,
        "forecast_simulation_intervals",
        base
        + (
            ("team_id", "VARCHAR"),
            ("estimate", "VARCHAR"),
            ("level", "INTEGER"),
            ("lower", "DOUBLE"),
            ("upper", "DOUBLE"),
        ),
        rows["forecast_simulation_intervals"],
    )
    _create_table(
        connection,
        "forecast_simulation_match_frequencies",
        base
        + (
            ("match_id", "VARCHAR"),
            ("p_home", "DOUBLE"),
            ("p_draw", "DOUBLE"),
            ("p_away", "DOUBLE"),
        ),
        rows["forecast_simulation_match_frequencies"],
    )
    _create_table(
        connection,
        "forecast_impact_fixtures",
        base
        + (
            ("match_id", "VARCHAR"),
            ("match_date", "DATE"),
            ("kickoff_time", "TIMESTAMPTZ"),
            ("home_team_id", "VARCHAR"),
            ("away_team_id", "VARCHAR"),
            ("status", "VARCHAR"),
            ("outcome", "VARCHAR"),
            ("outcome_count_home", "INTEGER"),
            ("outcome_count_draw", "INTEGER"),
            ("outcome_count_away", "INTEGER"),
            ("sufficient_sample", "BOOLEAN"),
            ("max_standard_error", "DOUBLE"),
            ("top_rms_movement", "DOUBLE"),
            ("unavailable_reason", "VARCHAR"),
            ("carried_from_forecast_id", "VARCHAR"),
            ("carried_from_generated_at", "TIMESTAMPTZ"),
            ("impact_horizon_days", "INTEGER"),
            ("impact_window_start", "TIMESTAMPTZ"),
            ("impact_window_end", "TIMESTAMPTZ"),
            ("impact_coverage", "VARCHAR"),
            ("minimum_conditional_samples", "INTEGER"),
        ),
        rows["forecast_impact_fixtures"],
    )
    _create_table(
        connection,
        "forecast_impacts",
        base
        + (
            ("match_id", "VARCHAR"),
            ("event", "VARCHAR"),
            ("team_id", "VARCHAR"),
            ("outcome", "VARCHAR"),
            ("baseline", "DOUBLE"),
            ("conditional_probability", "DOUBLE"),
            ("rms_movement", "DOUBLE"),
            ("carried_from_forecast_id", "VARCHAR"),
            ("carried_from_generated_at", "TIMESTAMPTZ"),
        ),
        rows["forecast_impacts"],
    )


def _install_hindcasts(connection, rows: dict[str, list]) -> None:
    base = (
        ("hindcast_id", "VARCHAR"),
        ("competition_id", "VARCHAR"),
        ("season_id", "VARCHAR"),
        ("model_version", "VARCHAR"),
        ("origin_at", "TIMESTAMPTZ"),
    )
    _create_table(
        connection,
        "hindcast_origins",
        base
        + (
            ("retrospective", "BOOLEAN"),
            ("generated_at", "TIMESTAMPTZ"),
            ("model_results_cutoff", "DATE"),
            ("simulations", "INTEGER"),
            ("played_matches", "INTEGER"),
            ("remaining_matches", "INTEGER"),
            ("public_href", "VARCHAR"),
            ("private_key", "VARCHAR"),
        ),
        rows["hindcast_origins"],
    )
    _create_table(connection, "hindcast_teams", base + TEAM_COLUMNS, rows["hindcast_teams"])
    for suffix, value_column in (
        ("team_events", (("event", "VARCHAR"),)),
        ("points_distribution", (("points", "INTEGER"),)),
        ("position_distribution", (("position", "INTEGER"),)),
    ):
        _create_table(
            connection,
            f"hindcast_{suffix}",
            base + (("team_id", "VARCHAR"),) + value_column + (("probability", "DOUBLE"),),
            rows[f"hindcast_{suffix}"],
        )
    _create_table(
        connection,
        "hindcast_intervals",
        base
        + (
            ("team_id", "VARCHAR"),
            ("estimate", "VARCHAR"),
            ("level", "INTEGER"),
            ("lower", "DOUBLE"),
            ("upper", "DOUBLE"),
        ),
        rows["hindcast_intervals"],
    )
    _create_table(
        connection,
        "hindcast_simulation_runs",
        base
        + (
            ("simulations", "INTEGER"),
            ("seed", "BIGINT"),
            ("as_of", "DATE"),
            ("results_observed_at", "TIMESTAMPTZ"),
            ("played_matches", "INTEGER"),
            ("remaining_matches", "INTEGER"),
            ("state_uncertainty", "VARCHAR"),
            ("future_state_evolution", "BOOLEAN"),
            ("head_to_head_applied_rate", "DOUBLE"),
            ("unresolved_decisive_tie_rate", "DOUBLE"),
            ("ranking_rules", "JSON"),
            ("ranking_diagnostics", "JSON"),
            ("tie_diagnostics", "JSON"),
            ("point_adjustments", "JSON"),
            ("assumptions", "JSON"),
            ("playoff_model", "JSON"),
            ("europe_scenario", "JSON"),
        ),
        rows["hindcast_simulation_runs"],
    )
    _create_table(
        connection,
        "hindcast_simulation_teams",
        base + TEAM_COLUMNS,
        rows["hindcast_simulation_teams"],
    )
    for suffix, value_column in (
        ("team_events", (("event", "VARCHAR"),)),
        ("points_distribution", (("points", "INTEGER"),)),
        ("position_distribution", (("position", "INTEGER"),)),
        ("goal_difference_distribution", (("goal_difference", "INTEGER"),)),
        ("europe_probabilities", (("scenario", "VARCHAR"),)),
    ):
        _create_table(
            connection,
            f"hindcast_simulation_{suffix}",
            base + (("team_id", "VARCHAR"),) + value_column + (("probability", "DOUBLE"),),
            rows[f"hindcast_simulation_{suffix}"],
        )
    _create_table(
        connection,
        "hindcast_simulation_intervals",
        base
        + (
            ("team_id", "VARCHAR"),
            ("estimate", "VARCHAR"),
            ("level", "INTEGER"),
            ("lower", "DOUBLE"),
            ("upper", "DOUBLE"),
        ),
        rows["hindcast_simulation_intervals"],
    )
    _create_table(
        connection,
        "hindcast_simulation_match_frequencies",
        base
        + (
            ("match_id", "VARCHAR"),
            ("p_home", "DOUBLE"),
            ("p_draw", "DOUBLE"),
            ("p_away", "DOUBLE"),
        ),
        rows["hindcast_simulation_match_frequencies"],
    )


def _install_match_hindcasts(connection, rows: dict[str, list]) -> None:
    base = (
        ("model_version", "VARCHAR"),
        ("competition_id", "VARCHAR"),
        ("season_id", "VARCHAR"),
        ("match_id", "VARCHAR"),
    )
    _create_table(
        connection,
        "match_hindcasts",
        base
        + (
            ("retrospective", "BOOLEAN"),
            ("match_date", "DATE"),
            ("kickoff_time", "TIMESTAMPTZ"),
            ("home_team_id", "VARCHAR"),
            ("away_team_id", "VARCHAR"),
            ("origin_at", "TIMESTAMPTZ"),
            ("model_results_cutoff", "DATE"),
            ("prospective_from", "DATE"),
            ("p_home", "DOUBLE"),
            ("p_draw", "DOUBLE"),
            ("p_away", "DOUBLE"),
            ("unadjusted_p_home", "DOUBLE"),
            ("unadjusted_p_draw", "DOUBLE"),
            ("unadjusted_p_away", "DOUBLE"),
            ("personnel_applied", "BOOLEAN"),
            ("home_discontinuity", "DOUBLE"),
            ("away_discontinuity", "DOUBLE"),
            ("home_log_rate_shift", "DOUBLE"),
            ("home_rate", "DOUBLE"),
            ("away_rate", "DOUBLE"),
            ("omitted_probability", "DOUBLE"),
            ("public_href", "VARCHAR"),
        ),
        rows["match_hindcasts"],
    )
    _create_table(
        connection,
        "match_hindcast_score_grid",
        base
        + (
            ("home_goals", "INTEGER"),
            ("away_goals", "INTEGER"),
            ("probability", "DOUBLE"),
        ),
        rows["match_hindcast_score_grid"],
    )


def _install_record(connection, matches: list[dict], summaries: list[dict]) -> None:
    _create_table(
        connection,
        "record_matches",
        (
            ("record_state", "VARCHAR"),
            ("match_id", "VARCHAR"),
            ("competition_id", "VARCHAR"),
            ("season_id", "VARCHAR"),
            ("forecast_id", "VARCHAR"),
            ("generated_at", "TIMESTAMPTZ"),
            ("kickoff_time", "TIMESTAMPTZ"),
            ("model_version", "VARCHAR"),
            ("p_home", "DOUBLE"),
            ("p_draw", "DOUBLE"),
            ("p_away", "DOUBLE"),
            ("outcome", "VARCHAR"),
        ),
        matches,
    )
    _create_table(
        connection,
        "record_summary",
        (
            ("scope", "VARCHAR"),
            ("scored", "INTEGER"),
            ("log_loss", "DOUBLE"),
            ("brier", "DOUBLE"),
            ("classwise_ece", "DOUBLE"),
            ("metrics", "JSON"),
        ),
        summaries,
    )


def _validate_analysis(connection) -> None:
    grains = {
        "forecasts": "forecast_id, competition_id",
        "forecast_matches": "forecast_id, competition_id, match_id",
        "forecast_match_stages": "forecast_id, competition_id, match_id, stage",
        "forecast_score_distributions": "forecast_id, competition_id, match_id, stage",
        "forecast_score_grid": "forecast_id, competition_id, match_id, stage, home_goals, away_goals",
        "forecast_personnel_teams": "forecast_id, competition_id, match_id, team_id",
        "forecast_personnel_players": "forecast_id, competition_id, match_id, team_id, player_id",
        "forecast_personnel_evidence": "forecast_id, competition_id, match_id, team_id, player_id, evidence_kind, ordinal",
        "forecast_personnel_reference_matches": "forecast_id, competition_id, match_id, team_id, reference_match_id",
        "forecast_market_inputs": "forecast_id, competition_id, match_id",
        "forecast_teams": "forecast_id, competition_id, team_id",
        "forecast_team_events": "forecast_id, competition_id, team_id, event",
        "forecast_points_distribution": "forecast_id, competition_id, team_id, points",
        "forecast_position_distribution": "forecast_id, competition_id, team_id, position",
        "forecast_intervals": "forecast_id, competition_id, team_id, estimate, level",
        "model_team_states": "forecast_id, competition_id, team_id",
        "forecast_runs": "forecast_id, competition_id",
        "model_specifications": "forecast_id, competition_id, specification_index",
        "forecast_simulation_runs": "forecast_id, competition_id",
        "forecast_simulation_teams": "forecast_id, competition_id, team_id",
        "forecast_simulation_team_events": "forecast_id, competition_id, team_id, event",
        "forecast_simulation_points_distribution": "forecast_id, competition_id, team_id, points",
        "forecast_simulation_position_distribution": "forecast_id, competition_id, team_id, position",
        "forecast_simulation_goal_difference_distribution": "forecast_id, competition_id, team_id, goal_difference",
        "forecast_simulation_intervals": "forecast_id, competition_id, team_id, estimate, level",
        "forecast_simulation_europe_probabilities": "forecast_id, competition_id, team_id, scenario",
        "forecast_simulation_match_frequencies": "forecast_id, competition_id, match_id",
        "forecast_impact_fixtures": "forecast_id, competition_id, match_id",
        "forecast_impacts": "forecast_id, competition_id, match_id, event, team_id, outcome",
        "hindcast_origins": "hindcast_id, competition_id, season_id, model_version",
        "hindcast_teams": "hindcast_id, competition_id, season_id, model_version, team_id",
        "hindcast_team_events": "hindcast_id, competition_id, season_id, model_version, team_id, event",
        "hindcast_points_distribution": "hindcast_id, competition_id, season_id, model_version, team_id, points",
        "hindcast_position_distribution": "hindcast_id, competition_id, season_id, model_version, team_id, position",
        "hindcast_intervals": "hindcast_id, competition_id, season_id, model_version, team_id, estimate, level",
        "hindcast_simulation_runs": "hindcast_id, competition_id, season_id, model_version",
        "hindcast_simulation_teams": "hindcast_id, competition_id, season_id, model_version, team_id",
        "hindcast_simulation_team_events": "hindcast_id, competition_id, season_id, model_version, team_id, event",
        "hindcast_simulation_points_distribution": "hindcast_id, competition_id, season_id, model_version, team_id, points",
        "hindcast_simulation_position_distribution": "hindcast_id, competition_id, season_id, model_version, team_id, position",
        "hindcast_simulation_goal_difference_distribution": "hindcast_id, competition_id, season_id, model_version, team_id, goal_difference",
        "hindcast_simulation_intervals": "hindcast_id, competition_id, season_id, model_version, team_id, estimate, level",
        "hindcast_simulation_europe_probabilities": "hindcast_id, competition_id, season_id, model_version, team_id, scenario",
        "hindcast_simulation_match_frequencies": "hindcast_id, competition_id, season_id, model_version, match_id",
        "match_hindcasts": "model_version, competition_id, season_id, match_id",
        "match_hindcast_score_grid": "model_version, competition_id, season_id, match_id, home_goals, away_goals",
        "record_matches": "record_state, match_id",
        "record_summary": "scope",
    }
    for table, keys in grains.items():
        duplicate = connection.execute(
            f"SELECT 1 FROM analysis.{table} GROUP BY {keys} HAVING count(*) > 1 LIMIT 1"
        ).fetchone()
        if duplicate:
            raise ValueError(f"Duplicate declared grain in analysis.{table}")
    probability_checks = {
        "forecast_matches": "abs(structural_p_home + structural_p_draw + structural_p_away - 1) > 0.000002 OR (market_assisted_p_home IS NOT NULL AND abs(market_assisted_p_home + market_assisted_p_draw + market_assisted_p_away - 1) > 0.000002)",
        "forecast_match_stages": "available AND abs(p_home + p_draw + p_away - 1) > 0.000002",
        "record_matches": "abs(p_home + p_draw + p_away - 1) > 0.000002",
        "match_hindcasts": "abs(p_home + p_draw + p_away - 1) > 0.000002 OR abs(unadjusted_p_home + unadjusted_p_draw + unadjusted_p_away - 1) > 0.000002",
    }
    for table, predicate in probability_checks.items():
        if connection.execute(
            f"SELECT 1 FROM analysis.{table} WHERE {predicate} LIMIT 1"
        ).fetchone():
            raise ValueError(f"Invalid probability sum in analysis.{table}")
    if connection.execute(
        """
        SELECT 1 FROM analysis.match_hindcasts hindcast
        JOIN (
            SELECT model_version, competition_id, season_id, match_id,
                   sum(probability) AS grid_probability
            FROM analysis.match_hindcast_score_grid
            GROUP BY model_version, competition_id, season_id, match_id
        ) grid USING (model_version, competition_id, season_id, match_id)
        WHERE abs(grid_probability + omitted_probability - 1) > 0.000002
        LIMIT 1
        """
    ).fetchone():
        raise ValueError("Invalid score distribution total in analysis.match_hindcast_score_grid")
    if connection.execute(
        "SELECT 1 FROM analysis.match_hindcasts WHERE match_date >= prospective_from LIMIT 1"
    ).fetchone():
        raise ValueError("A retrospective match forecast reaches prospective coverage")
    if connection.execute(
        "SELECT 1 FROM analysis.match_hindcasts hindcast "
        "JOIN analysis.record_matches record USING (match_id, model_version) LIMIT 1"
    ).fetchone():
        raise ValueError("A retrospective match forecast also appears in the prospective record")
    if connection.execute(
        """
        SELECT 1 FROM analysis.forecast_score_distributions distribution
        JOIN (
            SELECT forecast_id, competition_id, season_id, match_id, stage,
                   sum(probability) AS grid_probability
            FROM analysis.forecast_score_grid
            GROUP BY forecast_id, competition_id, season_id, match_id, stage
        ) grid USING (forecast_id, competition_id, season_id, match_id, stage)
        WHERE abs(grid_probability + omitted_probability - 1) > 0.000002
        LIMIT 1
        """
    ).fetchone():
        raise ValueError("Invalid score distribution total in analysis.forecast_score_grid")
    if connection.execute(
        """
        SELECT 1
        FROM analysis.forecast_match_stages stage
        JOIN analysis.forecasts forecast
          USING (forecast_id, competition_id, season_id)
        JOIN analysis.forecast_score_distributions distribution
          USING (forecast_id, competition_id, season_id, match_id, stage)
        JOIN (
            SELECT forecast_id, competition_id, season_id, match_id, stage,
                   sum(probability) FILTER (home_goals > away_goals) AS p_home,
                   sum(probability) FILTER (home_goals = away_goals) AS p_draw,
                   sum(probability) FILTER (home_goals < away_goals) AS p_away
            FROM analysis.forecast_score_grid
            GROUP BY forecast_id, competition_id, season_id, match_id, stage
        ) grid USING (forecast_id, competition_id, season_id, match_id, stage)
        WHERE forecast.private_schema_version >= 2
          AND greatest(abs(stage.p_home - grid.p_home), abs(stage.p_draw - grid.p_draw),
                       abs(stage.p_away - grid.p_away)) > distribution.omitted_probability + 0.000002
        LIMIT 1
        """
    ).fetchone():
        raise ValueError("Score grid does not reproduce its match-stage probabilities")
    if connection.execute(
        """
        SELECT 1
        FROM analysis.forecast_match_stages original
        JOIN analysis.forecast_match_stages adjusted
          USING (forecast_id, competition_id, season_id, match_id)
        JOIN analysis.forecasts forecast
          USING (forecast_id, competition_id, season_id)
        WHERE original.stage = 'unadjusted'
          AND adjusted.stage = 'personnel_adjusted'
          AND forecast.private_schema_version >= 2
          AND coalesce(adjusted.home_log_rate_shift, 0) = 0
          AND greatest(abs(original.p_home - adjusted.p_home),
                       abs(original.p_draw - adjusted.p_draw),
                       abs(original.p_away - adjusted.p_away)) > 0.000002
        LIMIT 1
        """
    ).fetchone():
        raise ValueError("A neutral personnel stage differs from its unadjusted stage")
    if connection.execute(
        """
        SELECT 1 FROM (
            SELECT forecast_id, competition_id, season_id, match_id,
                   max(discontinuity) FILTER (side = 'home') AS home_discontinuity,
                   max(discontinuity) FILTER (side = 'away') AS away_discontinuity,
                   max(kappa) AS kappa,
                   max(home_log_rate_shift) AS shift,
                   bool_and(usable_for_shift) AS usable
            FROM analysis.forecast_personnel_teams
            GROUP BY forecast_id, competition_id, season_id, match_id
        )
        WHERE usable AND kappa IS NOT NULL AND shift IS NOT NULL
          AND abs(shift - kappa * (away_discontinuity - home_discontinuity)) > 0.000002
        LIMIT 1
        """
    ).fetchone():
        raise ValueError("Personnel log-rate shift does not match the discontinuity difference")
    if connection.execute(
        """
        SELECT 1 FROM analysis.forecast_personnel_teams team
        JOIN (
            SELECT forecast_id, competition_id, season_id, match_id, team_id,
                   sum(discontinuity_contribution) AS total
            FROM analysis.forecast_personnel_players
            WHERE discontinuity_contribution IS NOT NULL
            GROUP BY forecast_id, competition_id, season_id, match_id, team_id
        ) players USING (forecast_id, competition_id, season_id, match_id, team_id)
        WHERE team.discontinuity IS NOT NULL AND abs(team.discontinuity - players.total) > 0.000002
        LIMIT 1
        """
    ).fetchone():
        raise ValueError("Personnel contributions do not reproduce team discontinuity")
    for prefix in ("forecast", "hindcast"):
        identity = (
            "forecast_id, competition_id, team_id"
            if prefix == "forecast"
            else ("hindcast_id, competition_id, season_id, model_version, team_id")
        )
        for distribution in ("points", "position"):
            if connection.execute(
                f"SELECT 1 FROM analysis.{prefix}_{distribution}_distribution "
                f"GROUP BY {identity} HAVING abs(sum(probability) - 1) > 0.0001 LIMIT 1"
            ).fetchone():
                raise ValueError(
                    f"Invalid distribution total in analysis.{prefix}_{distribution}_distribution"
                )
        missing_child = connection.execute(
            f"SELECT 1 FROM analysis.{prefix}_team_events child "
            f"LEFT JOIN analysis.{prefix}_teams parent USING ({identity}) "
            f"WHERE parent.team_id IS NULL LIMIT 1"
        ).fetchone()
        if missing_child:
            raise ValueError(f"Unknown team identity in analysis.{prefix}_team_events")


def current_model_version(publish_store) -> str | None:
    """The public model version of the newest live forecast, or None when there is none."""
    current = publish_store.get_json("forecasts/current.json") or {}
    pointers = [row for row in current.get("forecasts", ()) if row.get("model_version")]
    if not pointers:
        return None
    newest = max(pointers, key=lambda row: (row["generated_at"], row["forecast_id"]))
    return newest["model_version"]


def _install_projection_view(connection) -> None:
    connection.execute(
        """
        CREATE VIEW analysis.team_projections AS
        SELECT 'live' AS product, false AS retrospective, f.forecast_id,
               NULL::VARCHAR AS hindcast_id, f.competition_id, f.season_id,
               f.public_model_version AS model_version, f.generated_at,
               NULL::TIMESTAMPTZ AS origin_at, f.state_observed_at, f.model_results_cutoff,
               t.team_id, t.team_name, t.played, t.current_points, t.mean_points,
               t.median_points, t.mean_position, t.median_position, t.position_sd,
               t.mean_goal_difference
        FROM analysis.forecast_teams t JOIN analysis.forecasts f
        USING (forecast_id, competition_id, season_id)
        UNION ALL
        SELECT 'hindcast' AS product, true AS retrospective, NULL::VARCHAR AS forecast_id,
               h.hindcast_id, h.competition_id, h.season_id, h.model_version,
               h.generated_at, h.origin_at,
               NULL::TIMESTAMPTZ AS state_observed_at, h.model_results_cutoff,
               t.team_id, t.team_name, t.played, t.current_points, t.mean_points,
               t.median_points, t.mean_position, t.median_position, t.position_sd,
               t.mean_goal_difference
        FROM analysis.hindcast_teams t JOIN analysis.hindcast_origins h
        USING (hindcast_id, competition_id, season_id, model_version, origin_at)
        """
    )


def _install_match_stage_comparison(connection) -> None:
    connection.execute(
        """
        CREATE VIEW analysis.forecast_match_stage_comparison AS
        WITH stages AS (
            SELECT forecast_id, competition_id, season_id, match_id,
                   max(p_home) FILTER (stage = 'unadjusted') AS unadjusted_p_home,
                   max(p_draw) FILTER (stage = 'unadjusted') AS unadjusted_p_draw,
                   max(p_away) FILTER (stage = 'unadjusted') AS unadjusted_p_away,
                   max(home_rate) FILTER (stage = 'unadjusted') AS unadjusted_home_rate,
                   max(away_rate) FILTER (stage = 'unadjusted') AS unadjusted_away_rate,
                   max(p_home) FILTER (stage = 'personnel_adjusted') AS personnel_adjusted_p_home,
                   max(p_draw) FILTER (stage = 'personnel_adjusted') AS personnel_adjusted_p_draw,
                   max(p_away) FILTER (stage = 'personnel_adjusted') AS personnel_adjusted_p_away,
                   max(home_rate) FILTER (stage = 'personnel_adjusted') AS personnel_adjusted_home_rate,
                   max(away_rate) FILTER (stage = 'personnel_adjusted') AS personnel_adjusted_away_rate,
                   max(p_home) FILTER (stage = 'market_assisted') AS market_assisted_p_home,
                   max(p_draw) FILTER (stage = 'market_assisted') AS market_assisted_p_draw,
                   max(p_away) FILTER (stage = 'market_assisted') AS market_assisted_p_away,
                   bool_or(personnel_applied) AS personnel_applied,
                   max(home_log_rate_shift) AS home_log_rate_shift
            FROM analysis.forecast_match_stages
            GROUP BY forecast_id, competition_id, season_id, match_id
        ), personnel AS (
            SELECT forecast_id, competition_id, season_id, match_id,
                   max(discontinuity) FILTER (side = 'home') AS D_home,
                   max(discontinuity) FILTER (side = 'away') AS D_away,
                   max(kappa) AS kappa
            FROM analysis.forecast_personnel_teams
            GROUP BY forecast_id, competition_id, season_id, match_id
        )
        SELECT stages.*, personnel.D_home, personnel.D_away, personnel.kappa
        FROM stages LEFT JOIN personnel
        USING (forecast_id, competition_id, season_id, match_id)
        """
    )


def _install_match_hindcast_view(connection) -> None:
    """The retrospective match forecast beside the realized result, for scoring it.

    It is a separate product from `analysis.record_matches`. Nothing unions the two, because a
    retrospective forecast must never read as a prospective one.
    """
    connection.execute(
        """
        CREATE VIEW analysis.match_hindcast_outcomes AS
        SELECT h.model_version, h.competition_id, h.season_id, h.match_id, h.retrospective,
               h.match_date, h.kickoff_time, h.home_team_id, h.away_team_id, h.origin_at,
               h.model_results_cutoff, h.prospective_from, h.p_home, h.p_draw, h.p_away,
               h.unadjusted_p_home, h.unadjusted_p_draw, h.unadjusted_p_away,
               h.personnel_applied, h.home_log_rate_shift, h.home_rate, h.away_rate,
               m.status, m.home_goals, m.away_goals,
               CASE WHEN m.status <> 'finished' THEN NULL
                    WHEN m.home_goals > m.away_goals THEN 'H'
                    WHEN m.home_goals = m.away_goals THEN 'D' ELSE 'A' END AS outcome
        FROM analysis.match_hindcasts h
        LEFT JOIN analysis.matches m USING (match_id)
        """
    )


def _install_artifact_views(connection) -> None:
    has_players = connection.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = 'players' LIMIT 1"
    ).fetchone()
    if has_players:
        connection.execute(
            """
            UPDATE analysis.forecast_personnel_players AS target
            SET player_name = players.name
            FROM players
            WHERE target.player_id = players.player_id AND target.player_name IS NULL
            """
        )
    _install_projection_view(connection)
    _install_match_stage_comparison(connection)
    _install_match_hindcast_view(connection)


def install_artifact_analysis(
    connection, data_store, publish_store, hindcast_model_versions: frozenset | None = None
) -> tuple[dict, set[str], set[str]]:
    live, live_updates, live_versions = _live_rows(data_store, publish_store)
    hindcasts, hindcast_updates, hindcast_versions = _hindcast_rows(
        data_store, publish_store, hindcast_model_versions
    )
    match_hindcasts, match_updates, match_versions = _match_hindcast_rows(
        publish_store, hindcast_model_versions
    )
    record_matches, record_summary, record_updates = _record_rows(publish_store)
    _install_live(connection, live)
    _install_hindcasts(connection, hindcasts)
    _install_match_hindcasts(connection, match_hindcasts)
    _install_record(connection, record_matches, record_summary)
    _validate_analysis(connection)
    _install_artifact_views(connection)
    publication_updates = {**live_updates, **hindcast_updates, **match_updates, **record_updates}
    return (
        publication_updates,
        live_versions | hindcast_versions | match_versions,
        hindcast_versions | match_versions,
    )
