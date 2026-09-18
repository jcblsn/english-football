"""Store forecast results at declared analytical grains."""

import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from epl_forecast.datasets import SESSION_TIME_ZONE
from epl_forecast.storage import json_bytes, sha256_bytes

RESULT_SCHEMA_VERSION = 1


def install_result_schema(connection) -> None:
    connection.execute("CREATE SCHEMA IF NOT EXISTS forecast_result")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS forecast_result.forecast_runs (
            result_id VARCHAR PRIMARY KEY,
            competition_id VARCHAR NOT NULL,
            season_id VARCHAR NOT NULL,
            state_observed_at TIMESTAMPTZ NOT NULL,
            model_results_cutoff DATE NOT NULL,
            generated_at TIMESTAMPTZ NOT NULL,
            model_id VARCHAR NOT NULL,
            model_kind VARCHAR NOT NULL,
            input_revision VARCHAR NOT NULL,
            model_spec JSON NOT NULL,
            simulation_settings JSON NOT NULL,
            simulation_metadata JSON NOT NULL,
            software_provenance JSON NOT NULL,
            fit_diagnostics JSON NOT NULL,
            source_document_sha256 VARCHAR NOT NULL,
            schema_version INTEGER NOT NULL,
            stored_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS forecast_result.forecast_matches (
            result_id VARCHAR NOT NULL,
            match_id VARCHAR NOT NULL,
            home_team_id VARCHAR NOT NULL,
            away_team_id VARCHAR NOT NULL,
            match_date DATE,
            kickoff_time TIMESTAMPTZ,
            status VARCHAR NOT NULL,
            primary_stage VARCHAR NOT NULL,
            personnel_applied BOOLEAN NOT NULL,
            home_discontinuity DOUBLE,
            away_discontinuity DOUBLE,
            home_log_rate_shift DOUBLE,
            PRIMARY KEY (result_id, match_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS forecast_result.forecast_match_probabilities (
            result_id VARCHAR NOT NULL,
            match_id VARCHAR NOT NULL,
            stage VARCHAR NOT NULL,
            parent_stage VARCHAR,
            score_generating BOOLEAN NOT NULL,
            p_home DOUBLE NOT NULL,
            p_draw DOUBLE NOT NULL,
            p_away DOUBLE NOT NULL,
            PRIMARY KEY (result_id, match_id, stage)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS forecast_result.forecast_score_metadata (
            result_id VARCHAR NOT NULL,
            match_id VARCHAR NOT NULL,
            stage VARCHAR NOT NULL,
            home_rate DOUBLE,
            away_rate DOUBLE,
            omitted_probability DOUBLE NOT NULL,
            uncertainty_components JSON NOT NULL,
            PRIMARY KEY (result_id, match_id, stage)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS forecast_result.forecast_scores (
            result_id VARCHAR NOT NULL,
            match_id VARCHAR NOT NULL,
            stage VARCHAR NOT NULL,
            home_goals INTEGER NOT NULL,
            away_goals INTEGER NOT NULL,
            probability DOUBLE NOT NULL,
            PRIMARY KEY (result_id, match_id, stage, home_goals, away_goals)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS forecast_result.forecast_team_seasons (
            result_id VARCHAR NOT NULL,
            team_id VARCHAR NOT NULL,
            played INTEGER NOT NULL,
            current_points INTEGER NOT NULL,
            mean_points DOUBLE NOT NULL,
            median_points DOUBLE NOT NULL,
            mean_position DOUBLE NOT NULL,
            median_position DOUBLE NOT NULL,
            position_sd DOUBLE NOT NULL,
            mean_goal_difference DOUBLE NOT NULL,
            PRIMARY KEY (result_id, team_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS forecast_result.forecast_team_events (
            result_id VARCHAR NOT NULL,
            team_id VARCHAR NOT NULL,
            event VARCHAR NOT NULL,
            probability DOUBLE NOT NULL,
            PRIMARY KEY (result_id, team_id, event)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS forecast_result.forecast_team_points (
            result_id VARCHAR NOT NULL,
            team_id VARCHAR NOT NULL,
            points INTEGER NOT NULL,
            probability DOUBLE NOT NULL,
            PRIMARY KEY (result_id, team_id, points)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS forecast_result.forecast_team_positions (
            result_id VARCHAR NOT NULL,
            team_id VARCHAR NOT NULL,
            position INTEGER NOT NULL,
            probability DOUBLE NOT NULL,
            PRIMARY KEY (result_id, team_id, position)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS forecast_result.forecast_team_strengths (
            result_id VARCHAR NOT NULL,
            team_id VARCHAR NOT NULL,
            quality DOUBLE,
            tilt DOUBLE,
            attack_log_rate DOUBLE NOT NULL,
            defense_log_rate DOUBLE NOT NULL,
            attack_sd DOUBLE,
            defense_sd DOUBLE,
            training_matches INTEGER NOT NULL,
            state_source VARCHAR NOT NULL,
            detail JSON NOT NULL,
            PRIMARY KEY (result_id, team_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS forecast_result.forecast_conditionals (
            result_id VARCHAR NOT NULL,
            match_id VARCHAR NOT NULL,
            team_id VARCHAR NOT NULL,
            event VARCHAR NOT NULL,
            outcome VARCHAR NOT NULL,
            baseline_probability DOUBLE NOT NULL,
            conditional_probability DOUBLE NOT NULL,
            standard_error DOUBLE,
            rms_movement DOUBLE NOT NULL,
            swing DOUBLE NOT NULL,
            sufficient_sample BOOLEAN NOT NULL,
            PRIMARY KEY (result_id, match_id, team_id, event, outcome)
        )
        """
    )


def _json(value) -> str:
    return json.dumps(value, default=str, separators=(",", ":"), allow_nan=False)


def _validate_probability_set(row: dict, label: str) -> None:
    values = [float(row[key]) for key in ("p_home", "p_draw", "p_away")]
    if any(value < 0 or value > 1 for value in values) or abs(sum(values) - 1) > 1e-8:
        raise ValueError(f"Invalid match probability set: {label}")


def _integer_distribution(values):
    return (
        ((int(value), probability) for value, probability in values.items())
        if isinstance(values, dict)
        else enumerate(values)
    )


def _insert_match_rows(connection, result_id: str, matches: list[dict]) -> dict[str, int]:
    match_rows, probability_rows, metadata_rows, score_rows = [], [], [], []
    for match in matches:
        personnel = match.get("personnel") or {}
        home = personnel.get("home") or {}
        away = personnel.get("away") or {}
        match_rows.append(
            (
                result_id,
                match["match_id"],
                match["home_team_id"],
                match["away_team_id"],
                match.get("match_date"),
                match.get("kickoff_time"),
                match["status"],
                match.get("primary_probability_source", "structural"),
                personnel.get("home_log_rate_shift") is not None,
                home.get("discontinuity"),
                away.get("discontinuity"),
                personnel.get("home_log_rate_shift"),
            )
        )
        for stage, values in match["stages"].items():
            if values is None:
                continue
            _validate_probability_set(values, f"{match['match_id']}:{stage}")
            probability_rows.append(
                (
                    result_id,
                    match["match_id"],
                    stage,
                    values.get("parent_stage"),
                    values["score_generating"],
                    values["p_home"],
                    values["p_draw"],
                    values["p_away"],
                )
            )
            scores = values.get("score_distribution")
            if scores is None:
                continue
            metadata_rows.append(
                (
                    result_id,
                    match["match_id"],
                    stage,
                    scores.get("home_rate"),
                    scores.get("away_rate"),
                    scores["omitted_probability"],
                    _json(scores.get("uncertainty_components", {})),
                )
            )
            for home_goals, row in enumerate(scores["grid_home_rows_away_columns"]):
                for away_goals, probability in enumerate(row):
                    score_rows.append(
                        (
                            result_id,
                            match["match_id"],
                            stage,
                            home_goals,
                            away_goals,
                            probability,
                        )
                    )
    statements = (
        (
            "INSERT INTO forecast_result.forecast_matches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            match_rows,
        ),
        (
            "INSERT INTO forecast_result.forecast_match_probabilities VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            probability_rows,
        ),
        (
            "INSERT INTO forecast_result.forecast_score_metadata VALUES (?, ?, ?, ?, ?, ?, ?)",
            metadata_rows,
        ),
        (
            "INSERT INTO forecast_result.forecast_scores VALUES (?, ?, ?, ?, ?, ?)",
            score_rows,
        ),
    )
    for statement, rows in statements:
        if rows:
            connection.executemany(statement, rows)
    return {
        "matches": len(match_rows),
        "match_probabilities": len(probability_rows),
        "scores": len(score_rows),
    }


def _insert_team_rows(connection, result_id: str, forecast: dict) -> dict[str, int]:
    team_rows, event_rows, point_rows, position_rows, strength_rows = [], [], [], [], []
    for team in forecast["simulation"]["teams"]:
        team_rows.append(
            (
                result_id,
                team["team_id"],
                team["played"],
                team["current_points"],
                team["mean_points"],
                team["median_points"],
                team["mean_position"],
                team["median_position"],
                team["position_sd"],
                team["mean_goal_difference"],
            )
        )
        for event, probability in team.items():
            if event.endswith("_probability") and isinstance(probability, (int, float)):
                event_rows.append((result_id, team["team_id"], event, probability))
        for points, probability in _integer_distribution(team["points_distribution"]):
            if probability:
                point_rows.append((result_id, team["team_id"], points, probability))
        for position, probability in enumerate(team["position_probabilities"], start=1):
            if probability:
                position_rows.append((result_id, team["team_id"], position, probability))
    for strength in forecast["team_strengths"]:
        strength_rows.append(
            (
                result_id,
                strength["team_id"],
                strength.get("quality"),
                strength.get("tilt"),
                strength["attack_log_rate"],
                strength["defense_log_rate"],
                strength.get("attack_sd"),
                strength.get("defense_sd"),
                strength["training_matches"],
                strength["state_source"],
                _json(strength),
            )
        )
    statements = (
        (
            "INSERT INTO forecast_result.forecast_team_seasons VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            team_rows,
        ),
        (
            "INSERT INTO forecast_result.forecast_team_events VALUES (?, ?, ?, ?)",
            event_rows,
        ),
        (
            "INSERT INTO forecast_result.forecast_team_points VALUES (?, ?, ?, ?)",
            point_rows,
        ),
        (
            "INSERT INTO forecast_result.forecast_team_positions VALUES (?, ?, ?, ?)",
            position_rows,
        ),
        (
            "INSERT INTO forecast_result.forecast_team_strengths VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            strength_rows,
        ),
    )
    for statement, rows in statements:
        if rows:
            connection.executemany(statement, rows)
    return {
        "teams": len(team_rows),
        "events": len(event_rows),
        "points": len(point_rows),
        "positions": len(position_rows),
        "strengths": len(strength_rows),
    }


def _insert_conditionals(connection, result_id: str, forecast: dict) -> int:
    rows = []
    impacts = (forecast.get("simulation") or {}).get("match_impacts") or {}
    for fixture in impacts.get("fixtures", []):
        for impact in fixture["impacts"]:
            for outcome, probability in impact["conditional"].items():
                rows.append(
                    (
                        result_id,
                        fixture["match_id"],
                        impact["team_id"],
                        impact["event"],
                        outcome,
                        impact["baseline"],
                        probability,
                        impact.get("standard_error", {}).get(outcome),
                        impact["rms_movement"],
                        impact["swing"],
                        impact["sufficient_sample"],
                    )
                )
    if rows:
        connection.executemany(
            "INSERT INTO forecast_result.forecast_conditionals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    return len(rows)


def write_forecast_result(
    database: Path,
    forecast: dict,
    run: dict,
    *,
    input_revision: str,
    result_id: str | None = None,
) -> dict:
    """Write one forecast directly into typed, queryable result tables."""
    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    source_sha256 = sha256_bytes(json_bytes(forecast))
    result_id = result_id or source_sha256
    with duckdb.connect(str(database)) as connection:
        connection.execute(SESSION_TIME_ZONE)
        install_result_schema(connection)
        existing = connection.execute(
            "SELECT source_document_sha256 FROM forecast_result.forecast_runs WHERE result_id=?",
            [result_id],
        ).fetchone()
        if existing:
            if existing[0] != source_sha256:
                raise ValueError(f"Result ID already names different content: {result_id}")
            return {"result_id": result_id, "status": "unchanged"}
        model = forecast["model"]
        simulation = forecast["simulation"]
        settings = {
            key: run[key]
            for key in ("seed", "simulations", "max_goals", "europe_scenario", "adjustments")
            if key in run
        }
        simulation_metadata = {
            key: simulation.get(key)
            for key in (
                "assumptions",
                "ranking_rules",
                "ranking_rules_evidence",
                "point_adjustments",
                "playoff_model",
                "future_state_evolution",
                "state_uncertainty",
            )
        }
        provenance = {
            key: run.get(key)
            for key in (
                "code_sha256",
                "config_sha256",
                "package_version",
                "python",
                "dependencies",
                "execution",
            )
        }
        connection.execute("BEGIN TRANSACTION")
        try:
            connection.execute(
                "INSERT INTO forecast_result.forecast_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    result_id,
                    forecast["competition_id"],
                    forecast["season_id"],
                    forecast["state_observed_at"],
                    forecast["model_results_cutoff"],
                    forecast["generated_at"],
                    model["id"],
                    model["kind"],
                    input_revision,
                    _json(model),
                    _json(settings),
                    _json(simulation_metadata),
                    _json(provenance),
                    _json(forecast.get("fit_diagnostics", {})),
                    source_sha256,
                    RESULT_SCHEMA_VERSION,
                    datetime.now(UTC),
                ],
            )
            counts = _insert_match_rows(connection, result_id, forecast["matches"])
            counts.update(_insert_team_rows(connection, result_id, forecast))
            counts["conditionals"] = _insert_conditionals(connection, result_id, forecast)
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        connection.execute("CHECKPOINT")
    return {"result_id": result_id, "status": "written", **counts}
