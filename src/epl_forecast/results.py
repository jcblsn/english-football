"""Store forecast results at declared analytical grains."""

import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from epl_forecast.datasets import SESSION_TIME_ZONE
from epl_forecast.market import market_assisted_probabilities
from epl_forecast.storage import json_bytes, sha256_bytes

RESULT_SCHEMA_VERSION = 6


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
            stored_at TIMESTAMPTZ NOT NULL,
            forecast_metadata JSON,
            source_result_id VARCHAR,
            market_replacement BOOLEAN NOT NULL DEFAULT false
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS forecast_result.forecast_public_documents (
            result_id VARCHAR PRIMARY KEY,
            document JSON NOT NULL,
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
            model_forecast_date DATE,
            started BOOLEAN NOT NULL,
            primary_stage VARCHAR NOT NULL,
            personnel_applied BOOLEAN NOT NULL,
            home_discontinuity DOUBLE,
            away_discontinuity DOUBLE,
            home_log_rate_shift DOUBLE,
            personnel_detail JSON,
            PRIMARY KEY (result_id, match_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS forecast_result.forecast_team_names (
            result_id VARCHAR NOT NULL,
            team_id VARCHAR NOT NULL,
            name VARCHAR NOT NULL,
            PRIMARY KEY (result_id, team_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS forecast_result.forecast_unsettled_fixtures (
            result_id VARCHAR NOT NULL,
            match_id VARCHAR NOT NULL,
            home_team_id VARCHAR NOT NULL,
            away_team_id VARCHAR NOT NULL,
            match_date DATE,
            kickoff_time TIMESTAMPTZ,
            status VARCHAR NOT NULL,
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
            detail JSON,
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
            points_intervals JSON NOT NULL,
            points_quantiles_05_50_95 JSON NOT NULL,
            mean_position DOUBLE NOT NULL,
            median_position DOUBLE NOT NULL,
            position_sd DOUBLE NOT NULL,
            position_intervals JSON NOT NULL,
            mean_goal_difference DOUBLE NOT NULL,
            detail JSON,
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
            impact_order INTEGER NOT NULL,
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
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS forecast_result.forecast_impact_metadata (
            result_id VARCHAR PRIMARY KEY,
            simulations INTEGER NOT NULL,
            horizon_days INTEGER NOT NULL,
            window_start TIMESTAMPTZ,
            window_end TIMESTAMPTZ,
            coverage VARCHAR NOT NULL,
            minimum_conditional_samples INTEGER NOT NULL,
            smallest_outcome_count INTEGER NOT NULL,
            basis VARCHAR NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS forecast_result.forecast_impact_fixtures (
            result_id VARCHAR NOT NULL,
            match_id VARCHAR NOT NULL,
            home_team_id VARCHAR NOT NULL,
            away_team_id VARCHAR NOT NULL,
            match_date DATE,
            home_outcomes INTEGER NOT NULL,
            draw_outcomes INTEGER NOT NULL,
            away_outcomes INTEGER NOT NULL,
            top_rms_movement DOUBLE NOT NULL,
            PRIMARY KEY (result_id, match_id)
        )
        """
    )
    connection.execute(
        "ALTER TABLE forecast_result.forecast_runs ADD COLUMN IF NOT EXISTS forecast_metadata JSON"
    )
    connection.execute(
        "ALTER TABLE forecast_result.forecast_runs ADD COLUMN IF NOT EXISTS source_result_id VARCHAR"
    )
    connection.execute(
        "ALTER TABLE forecast_result.forecast_runs ADD COLUMN IF NOT EXISTS "
        "market_replacement BOOLEAN DEFAULT false"
    )
    connection.execute(
        "ALTER TABLE forecast_result.forecast_matches ADD COLUMN IF NOT EXISTS personnel_detail JSON"
    )
    connection.execute(
        "ALTER TABLE forecast_result.forecast_match_probabilities ADD COLUMN IF NOT EXISTS detail JSON"
    )
    connection.execute(
        "ALTER TABLE forecast_result.forecast_team_seasons ADD COLUMN IF NOT EXISTS detail JSON"
    )
    impact_columns = {
        row[1]: row[2]
        for row in connection.execute(
            "PRAGMA table_info('forecast_result.forecast_impact_metadata')"
        ).fetchall()
    }
    for column in ("window_start", "window_end"):
        if impact_columns[column] == "DATE":
            connection.execute(
                f"ALTER TABLE forecast_result.forecast_impact_metadata ALTER {column} "
                f"TYPE TIMESTAMPTZ USING {column}::TIMESTAMPTZ"
            )
    connection.execute(
        """
        UPDATE forecast_result.forecast_impact_metadata AS impact
        SET window_start = COALESCE(
                try_cast(json_extract_string(run.forecast_metadata, '$.impact_window.window_start') AS TIMESTAMPTZ),
                impact.window_start
            ),
            window_end = COALESCE(
                try_cast(json_extract_string(run.forecast_metadata, '$.impact_window.window_end') AS TIMESTAMPTZ),
                impact.window_end
            )
        FROM forecast_result.forecast_runs AS run
        WHERE impact.result_id = run.result_id
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


def _probability_stages(match: dict) -> dict:
    if "stages" in match:
        return match["stages"]
    structural = {
        "parent_stage": None,
        "score_generating": True,
        "p_home": match["p_home"],
        "p_draw": match["p_draw"],
        "p_away": match["p_away"],
        "score_distribution": match["score_distribution"],
    }
    assisted = match.get("market_assisted_probabilities")
    market = (
        None
        if assisted is None
        else {
            "parent_stage": "personnel_adjusted",
            "score_generating": False,
            **assisted,
        }
    )
    return {"personnel_adjusted": structural, "market_assisted": market}


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
                match.get("model_forecast_date"),
                bool(match.get("started", False)),
                match.get("primary_probability_source", "structural"),
                bool(personnel),
                home.get("discontinuity"),
                away.get("discontinuity"),
                personnel.get("home_log_rate_shift"),
                _json(match.get("personnel")) if match.get("personnel") is not None else None,
            )
        )
        for stage, values in _probability_stages(match).items():
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
                    _json(
                        {key: value for key, value in values.items() if key != "score_distribution"}
                    ),
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
            "INSERT INTO forecast_result.forecast_matches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            match_rows,
        ),
        (
            "INSERT INTO forecast_result.forecast_match_probabilities VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            probability_rows,
        ),
        (
            "INSERT INTO forecast_result.forecast_score_metadata VALUES (?, ?, ?, ?, ?, ?, ?)",
            metadata_rows,
        ),
    )
    for statement, rows in statements:
        if rows:
            connection.executemany(statement, rows)
    if score_rows:
        connection.execute(
            """
            INSERT INTO forecast_result.forecast_scores
            SELECT json_extract_string(value, '$[0]'),
                   json_extract_string(value, '$[1]'),
                   json_extract_string(value, '$[2]'),
                   CAST(json_extract(value, '$[3]') AS INTEGER),
                   CAST(json_extract(value, '$[4]') AS INTEGER),
                   CAST(json_extract(value, '$[5]') AS DOUBLE)
            FROM json_each(?)
            """,
            [_json(score_rows)],
        )
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
                _json(team.get("points_intervals", {})),
                _json(team.get("points_quantiles_05_50_95", {})),
                team["mean_position"],
                team["median_position"],
                team["position_sd"],
                _json(team.get("position_intervals", {})),
                team["mean_goal_difference"],
                _json(team),
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
            "INSERT INTO forecast_result.forecast_team_seasons VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
    if not impacts:
        return 0
    simulation = forecast["simulation"]
    connection.execute(
        "INSERT INTO forecast_result.forecast_impact_metadata VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            result_id,
            impacts.get("simulations", simulation["simulations"]),
            impacts.get("horizon_days", 0),
            impacts.get("window_start"),
            impacts.get("window_end"),
            impacts.get("coverage", "participants"),
            impacts.get("minimum_conditional_samples", 0),
            impacts.get("smallest_outcome_count", 0),
            impacts.get("basis", "same simulated season paths"),
        ],
    )
    match_index = {match["match_id"]: match for match in forecast["matches"]}
    fixture_rows = []
    for fixture in impacts.get("fixtures", []):
        match = match_index[fixture["match_id"]]
        counts = fixture.get("outcome_counts", {})
        fixture_rows.append(
            (
                result_id,
                fixture["match_id"],
                fixture.get("home_team_id", match["home_team_id"]),
                fixture.get("away_team_id", match["away_team_id"]),
                fixture.get("match_date", match.get("match_date")),
                counts.get("home", 0),
                counts.get("draw", 0),
                counts.get("away", 0),
                fixture.get("top_rms_movement", 0.0),
            )
        )
        for impact_order, impact in enumerate(fixture["impacts"]):
            for outcome, probability in impact["conditional"].items():
                rows.append(
                    (
                        result_id,
                        fixture["match_id"],
                        impact["team_id"],
                        impact["event"],
                        impact_order,
                        outcome,
                        impact["baseline"],
                        probability,
                        impact.get("standard_error", {}).get(outcome),
                        impact["rms_movement"],
                        impact["swing"],
                        impact["sufficient_sample"],
                    )
                )
    if fixture_rows:
        connection.executemany(
            "INSERT INTO forecast_result.forecast_impact_fixtures VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            fixture_rows,
        )
    if rows:
        connection.executemany(
            "INSERT INTO forecast_result.forecast_conditionals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            key: value for key, value in simulation.items() if key not in {"teams", "match_impacts"}
        }
        simulation_metadata["publication_context"] = {
            "competition_name": forecast["competition_name"],
            "unscheduled_placeholder": forecast.get("unscheduled_placeholder"),
            "unsettled_placeholder": forecast.get("unsettled_placeholder"),
            "impact_window": forecast.get("impact_window"),
        }
        simulation_metadata["state_uncertainty"] = simulation.get(
            "state_uncertainty", forecast.get("state_uncertainty")
        )
        simulation_metadata["simulations"] = simulation["simulations"]
        forecast_metadata = {
            key: value
            for key, value in forecast.items()
            if key
            not in {
                "matches",
                "simulation",
                "team_names",
                "team_strengths",
                "unsettled_fixtures",
            }
        }
        connection.execute("BEGIN TRANSACTION")
        try:
            connection.execute(
                "INSERT INTO forecast_result.forecast_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    _json(run),
                    _json(forecast.get("fit_diagnostics", {})),
                    source_sha256,
                    RESULT_SCHEMA_VERSION,
                    datetime.now(UTC),
                    _json(forecast_metadata),
                    None,
                    False,
                ],
            )
            counts = _insert_match_rows(connection, result_id, forecast["matches"])
            counts.update(_insert_team_rows(connection, result_id, forecast))
            connection.executemany(
                "INSERT INTO forecast_result.forecast_team_names VALUES (?, ?, ?)",
                [
                    (result_id, team_id, name)
                    for team_id, name in sorted(forecast["team_names"].items())
                ],
            )
            unsettled = [
                (
                    result_id,
                    row["match_id"],
                    row["home_team_id"],
                    row["away_team_id"],
                    row.get("match_date"),
                    row.get("kickoff_time"),
                    row["status"],
                )
                for row in forecast.get("unsettled_fixtures", [])
            ]
            if unsettled:
                connection.executemany(
                    "INSERT INTO forecast_result.forecast_unsettled_fixtures VALUES (?, ?, ?, ?, ?, ?, ?)",
                    unsettled,
                )
            counts["conditionals"] = _insert_conditionals(connection, result_id, forecast)
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        connection.execute("CHECKPOINT")
    return {"result_id": result_id, "status": "written", **counts}


def _decoded(value):
    return json.loads(value) if isinstance(value, str) else value


def _iso(value):
    return None if value is None else value.isoformat()


def store_public_projection(database: Path, result_id: str, document: dict) -> None:
    payload = _json(document)
    with duckdb.connect(str(database)) as connection:
        connection.execute(SESSION_TIME_ZONE)
        install_result_schema(connection)
        existing = connection.execute(
            "SELECT document FROM forecast_result.forecast_public_documents WHERE result_id = ?",
            [result_id],
        ).fetchone()
        if existing:
            if _decoded(existing[0]) != document:
                raise ValueError(f"Public result ID already names different content: {result_id}")
            return
        connection.execute(
            "INSERT INTO forecast_result.forecast_public_documents VALUES (?, ?, ?)",
            [result_id, payload, datetime.now(UTC)],
        )
        connection.execute("CHECKPOINT")


def read_public_projection(database: Path, result_id: str) -> dict:
    with duckdb.connect(str(database), read_only=True) as connection:
        row = connection.execute(
            "SELECT document FROM forecast_result.forecast_public_documents WHERE result_id = ?",
            [result_id],
        ).fetchone()
    if row is None:
        raise KeyError(f"Unknown public forecast result: {result_id}")
    return _decoded(row[0])


def _result_lineage(connection, result_id: str) -> list[str]:
    lineage = []
    current = result_id
    while current is not None:
        if current in lineage:
            raise ValueError(f"Forecast result lineage contains a cycle: {result_id}")
        lineage.append(current)
        row = connection.execute(
            "SELECT source_result_id FROM forecast_result.forecast_runs WHERE result_id = ?",
            [current],
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown forecast result: {current}")
        current = row[0]
    return lineage


def _is_market_replacement(connection, result_id: str) -> bool:
    columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info('forecast_result.forecast_runs')"
        ).fetchall()
    }
    if "market_replacement" not in columns:
        return False
    row = connection.execute(
        "SELECT coalesce(market_replacement, false) FROM forecast_result.forecast_runs "
        "WHERE result_id = ?",
        [result_id],
    ).fetchone()
    return bool(row and row[0])


def _effective_market_rows(connection, result_id: str) -> dict[str, tuple]:
    effective = {}
    for revision_id in reversed(_result_lineage(connection, result_id)):
        if _is_market_replacement(connection, revision_id):
            effective.clear()
        for row in connection.execute(
            "SELECT match_id, stage, parent_stage, score_generating, "
            "p_home, p_draw, p_away, detail FROM "
            "forecast_result.forecast_match_probabilities "
            "WHERE result_id = ? AND stage = 'market_assisted'",
            [revision_id],
        ).fetchall():
            effective[row[0]] = row
    return effective


def read_forecast_result(database: Path, result_id: str) -> dict:
    """Reconstruct the publication projection from typed result grains."""
    with duckdb.connect(str(database), read_only=True) as connection:
        connection.execute(SESSION_TIME_ZONE)
        run = connection.execute(
            """
            SELECT competition_id, season_id, state_observed_at, model_results_cutoff,
                   generated_at, model_spec, simulation_settings, simulation_metadata,
                   fit_diagnostics, forecast_metadata
            FROM forecast_result.forecast_runs WHERE result_id = ?
            """,
            [result_id],
        ).fetchone()
        if run is None:
            raise KeyError(f"Unknown forecast result: {result_id}")
        lineage = _result_lineage(connection, result_id)
        structural_result_id = lineage[-1]
        settings, metadata = _decoded(run[6]), _decoded(run[7])
        forecast_metadata = _decoded(run[9]) or {}
        context = metadata["publication_context"]
        names = {}
        for revision_id in lineage:
            names = dict(
                connection.execute(
                    "SELECT team_id, name FROM forecast_result.forecast_team_names WHERE result_id = ?",
                    [revision_id],
                ).fetchall()
            )
            if names:
                break
        stage_values = {}
        for revision_id in reversed(lineage):
            if _is_market_replacement(connection, revision_id):
                stage_values = {
                    key: value for key, value in stage_values.items() if key[1] != "market_assisted"
                }
            stage_values.update(
                {
                    (match_id, stage): {
                        "p_home": p_home,
                        "p_draw": p_draw,
                        "p_away": p_away,
                        "parent_stage": parent_stage,
                        "score_generating": score_generating,
                        **(_decoded(detail) or {}),
                    }
                    for match_id, stage, parent_stage, score_generating, p_home, p_draw, p_away, detail in connection.execute(
                        """
                        SELECT match_id, stage, parent_stage, score_generating,
                               p_home, p_draw, p_away, detail
                        FROM forecast_result.forecast_match_probabilities WHERE result_id = ?
                        """,
                        [revision_id],
                    ).fetchall()
                }
            )
        score_metadata = {
            (match_id, stage): (home_rate, away_rate, omitted, _decoded(uncertainty))
            for match_id, stage, home_rate, away_rate, omitted, uncertainty in connection.execute(
                """
                SELECT match_id, stage, home_rate, away_rate, omitted_probability,
                       uncertainty_components
                FROM forecast_result.forecast_score_metadata WHERE result_id = ?
                """,
                [structural_result_id],
            ).fetchall()
        }
        score_rows = connection.execute(
            """
            SELECT match_id, stage, home_goals, away_goals, probability
            FROM forecast_result.forecast_scores WHERE result_id = ?
            ORDER BY match_id, stage, home_goals, away_goals
            """,
            [structural_result_id],
        ).fetchall()
        score_grids = {}
        for match_id, stage, home_goals, away_goals, probability in score_rows:
            grid = score_grids.setdefault((match_id, stage), [])
            while len(grid) <= home_goals:
                grid.append([])
            while len(grid[home_goals]) <= away_goals:
                grid[home_goals].append(0.0)
            grid[home_goals][away_goals] = probability
        matches = []
        match_rows = connection.execute(
            """
            SELECT match_id, home_team_id, away_team_id, match_date, kickoff_time, status,
                   model_forecast_date, started, primary_stage, personnel_applied,
                   home_discontinuity, away_discontinuity, home_log_rate_shift, personnel_detail
            FROM forecast_result.forecast_matches WHERE result_id = ?
            ORDER BY kickoff_time NULLS LAST, match_id
            """,
            [structural_result_id],
        ).fetchall()
        if not match_rows:
            raise ValueError(f"Forecast result has no match detail: {result_id}")
        generated_at = run[4]
        seen = set()
        for row in match_rows:
            match_id, home_team_id, away_team_id = row[:3]
            primary = stage_values[match_id, "personnel_adjusted"]
            market = stage_values.get((match_id, "market_assisted"))
            score_key = (match_id, "personnel_adjusted")
            home_rate, away_rate, omitted, uncertainty = score_metadata[score_key]
            eligible = row[4] is not None and row[4] > generated_at
            next_for = (
                [team for team in (home_team_id, away_team_id) if team not in seen]
                if eligible
                else []
            )
            seen.update(next_for)
            personnel = _decoded(row[13]) or (
                {
                    "home": {"discontinuity": row[10]},
                    "away": {"discontinuity": row[11]},
                    "home_log_rate_shift": row[12],
                }
                if row[9]
                else None
            )
            stages = {}
            for stage in ("unadjusted", "personnel_adjusted", "market_assisted"):
                value = stage_values.get((match_id, stage))
                if value is None:
                    stages[stage] = None
                    continue
                stage_value = dict(value)
                metadata_key = (match_id, stage)
                if metadata_key in score_metadata:
                    stage_home_rate, stage_away_rate, stage_omitted, stage_uncertainty = (
                        score_metadata[metadata_key]
                    )
                    stage_value["score_distribution"] = {
                        "home_rate": stage_home_rate,
                        "away_rate": stage_away_rate,
                        "omitted_probability": stage_omitted,
                        "uncertainty_components": stage_uncertainty,
                        "grid_home_rows_away_columns": score_grids[metadata_key],
                    }
                stages[stage] = stage_value
            matches.append(
                {
                    "match_id": match_id,
                    "home_team_id": home_team_id,
                    "away_team_id": away_team_id,
                    "match_date": _iso(row[3]),
                    "kickoff_time": _iso(row[4]),
                    "status": row[5],
                    "model_forecast_date": _iso(row[6]),
                    "started": row[7],
                    **{key: primary[key] for key in ("p_home", "p_draw", "p_away")},
                    "stages": stages,
                    "market_assisted_probabilities": market,
                    "personnel": personnel,
                    "next_match_for_teams": next_for,
                    "score_distribution": {
                        "home_rate": home_rate,
                        "away_rate": away_rate,
                        "omitted_probability": omitted,
                        "uncertainty_components": uncertainty,
                        "grid_home_rows_away_columns": score_grids[score_key],
                    },
                }
            )
        team_rows = connection.execute(
            """
            SELECT team_id, played, current_points, mean_points, median_points,
                   points_intervals, points_quantiles_05_50_95, mean_position,
                   median_position, position_sd, position_intervals, mean_goal_difference,
                   detail
            FROM forecast_result.forecast_team_seasons
            WHERE result_id = ? ORDER BY mean_position
            """,
            [structural_result_id],
        ).fetchall()
        events = {}
        for team_id, event, probability in connection.execute(
            "SELECT team_id, event, probability FROM forecast_result.forecast_team_events WHERE result_id = ?",
            [structural_result_id],
        ).fetchall():
            events.setdefault(team_id, {})[event] = probability
        points = {}
        for team_id, value, probability in connection.execute(
            "SELECT team_id, points, probability FROM forecast_result.forecast_team_points WHERE result_id = ?",
            [structural_result_id],
        ).fetchall():
            points.setdefault(team_id, {})[str(value)] = probability
        positions = {}
        for team_id, position, probability in connection.execute(
            "SELECT team_id, position, probability FROM forecast_result.forecast_team_positions WHERE result_id = ?",
            [structural_result_id],
        ).fetchall():
            positions.setdefault(team_id, {})[position] = probability
        teams = []
        for row in team_rows:
            position_values = positions.get(row[0], {})
            position_probabilities = [
                position_values.get(position, 0.0) for position in range(1, len(team_rows) + 1)
            ]
            teams.append(
                {
                    **(_decoded(row[12]) or {}),
                    "team_id": row[0],
                    "played": row[1],
                    "current_points": row[2],
                    "mean_points": row[3],
                    "median_points": row[4],
                    "points_intervals": _decoded(row[5]),
                    "points_quantiles_05_50_95": _decoded(row[6]),
                    "mean_position": row[7],
                    "median_position": row[8],
                    "position_sd": row[9],
                    "position_intervals": _decoded(row[10]),
                    "mean_goal_difference": row[11],
                    "points_distribution": points.get(row[0], {}),
                    "position_probabilities": position_probabilities,
                    **events.get(row[0], {}),
                }
            )
        simulation = {
            **metadata,
            "simulations": settings.get("simulations", metadata["simulations"]),
            "teams": teams,
            "state_uncertainty": metadata.get("state_uncertainty"),
            "match_impacts": _read_impacts(
                connection,
                structural_result_id,
                forecast_metadata.get("impact_window") or context.get("impact_window"),
            ),
        }
        strengths = [
            {
                **(_decoded(row[9]) or {}),
                "team_id": row[0],
                "quality": row[1],
                "tilt": row[2],
                "attack_log_rate": row[3],
                "defense_log_rate": row[4],
                "attack_sd": row[5],
                "defense_sd": row[6],
                "training_matches": row[7],
                "state_source": row[8],
            }
            for row in connection.execute(
                """
                SELECT team_id, quality, tilt, attack_log_rate, defense_log_rate,
                       attack_sd, defense_sd, training_matches, state_source, detail
                FROM forecast_result.forecast_team_strengths
                WHERE result_id = ? ORDER BY team_id
                """,
                [structural_result_id],
            ).fetchall()
        ]
        unsettled = [
            {
                "match_id": row[0],
                "home_team_id": row[1],
                "away_team_id": row[2],
                "match_date": _iso(row[3]),
                "kickoff_time": _iso(row[4]),
                "status": row[5],
            }
            for row in connection.execute(
                """
                SELECT match_id, home_team_id, away_team_id, match_date, kickoff_time, status
                FROM forecast_result.forecast_unsettled_fixtures WHERE result_id = ?
                """,
                [structural_result_id],
            ).fetchall()
        ]
    return {
        **forecast_metadata,
        "competition_id": run[0],
        "competition_name": context["competition_name"],
        "season_id": run[1],
        "state_observed_at": _iso(run[2]),
        "model_results_cutoff": _iso(run[3]),
        "generated_at": _iso(run[4]),
        "model": _decoded(run[5]),
        "fit_diagnostics": _decoded(run[8]),
        "state_uncertainty": metadata.get("state_uncertainty"),
        "team_names": names,
        "team_strengths": strengths,
        "matches": matches,
        "simulation": simulation,
        "unscheduled_placeholder": context.get("unscheduled_placeholder"),
        "unsettled_placeholder": context.get("unsettled_placeholder"),
        "unsettled_fixtures": unsettled,
        "impact_window": forecast_metadata.get("impact_window") or context.get("impact_window"),
    }


def read_forecast_run(database: Path, result_id: str) -> dict:
    with duckdb.connect(str(database), read_only=True) as connection:
        row = connection.execute(
            "SELECT software_provenance, schema_version FROM forecast_result.forecast_runs "
            "WHERE result_id = ?",
            [result_id],
        ).fetchone()
    if row is None:
        raise KeyError(f"Unknown forecast result: {result_id}")
    return {**(_decoded(row[0]) or {}), "result_schema_version": row[1]}


def clone_forecast_result(
    database: Path,
    source_result_id: str,
    result_id: str,
    *,
    generated_at: datetime,
    observed_at: datetime,
    input_revision: str,
    software_provenance: dict,
    replace_market: bool = False,
    market_quotes: list[dict] | None = None,
    market_pool: dict | None = None,
    team_names: dict[str, str] | None = None,
) -> dict:
    """Create a result revision without repeating structural fit or season simulation."""
    identity = sha256_bytes(
        _json(
            {
                "source_result_id": source_result_id,
                "result_id": result_id,
                "generated_at": generated_at.isoformat(),
                "observed_at": observed_at.isoformat(),
                "input_revision": input_revision,
                "software_provenance": software_provenance,
                "replace_market": replace_market,
                "market_quotes": market_quotes,
                "market_pool": market_pool,
                "team_names": team_names,
            }
        ).encode()
    )
    with duckdb.connect(str(database)) as connection:
        connection.execute(SESSION_TIME_ZONE)
        install_result_schema(connection)
        existing = connection.execute(
            "SELECT source_document_sha256 FROM forecast_result.forecast_runs WHERE result_id = ?",
            [result_id],
        ).fetchone()
        if existing:
            if existing != (identity,):
                raise ValueError(f"Result ID already names different content: {result_id}")
            return {"result_id": result_id, "status": "unchanged"}
        if not connection.execute(
            "SELECT 1 FROM forecast_result.forecast_runs WHERE result_id = ?",
            [source_result_id],
        ).fetchone():
            raise KeyError(f"Unknown source forecast result: {source_result_id}")
        source_lineage = _result_lineage(connection, source_result_id)
        structural_result_id = source_lineage[-1]
        source_metadata = _decoded(
            connection.execute(
                "SELECT forecast_metadata FROM forecast_result.forecast_runs WHERE result_id = ?",
                [source_result_id],
            ).fetchone()[0]
        )
        connection.execute("BEGIN TRANSACTION")
        try:
            connection.execute(
                """
                INSERT INTO forecast_result.forecast_runs (
                    result_id, competition_id, season_id, state_observed_at,
                    model_results_cutoff, generated_at, model_id, model_kind,
                    input_revision, model_spec, simulation_settings, simulation_metadata,
                    software_provenance, fit_diagnostics, source_document_sha256,
                    schema_version, stored_at, forecast_metadata, source_result_id,
                    market_replacement
                )
                SELECT ?, competition_id, season_id, ?, model_results_cutoff,
                       ?, model_id, model_kind, ?, model_spec, simulation_settings,
                       simulation_metadata, ?, fit_diagnostics, ?, ?, ?, forecast_metadata, ?, true
                FROM forecast_result.forecast_runs WHERE result_id = ?
                """,
                [
                    result_id,
                    observed_at,
                    generated_at,
                    input_revision,
                    _json(software_provenance),
                    identity,
                    RESULT_SCHEMA_VERSION,
                    datetime.now(UTC),
                    structural_result_id,
                    source_result_id,
                ],
            )
            if replace_market:
                available = _insert_market_probabilities(
                    connection,
                    result_id,
                    market_quotes or [],
                    market_pool,
                    structural_result_id,
                )
                source_metadata["market_assistance"] = (
                    None
                    if market_pool is None
                    else {
                        **market_pool,
                        "available_match_forecasts": available,
                        "season_simulation_uses_market": False,
                    }
                )
            else:
                effective_market = _effective_market_rows(connection, source_result_id)
                if effective_market:
                    connection.executemany(
                        "INSERT INTO forecast_result.forecast_match_probabilities "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [
                            (result_id, *row)
                            for row in sorted(effective_market.values(), key=lambda item: item[0])
                        ],
                    )
            connection.execute(
                "UPDATE forecast_result.forecast_runs SET forecast_metadata = ? "
                "WHERE result_id = ?",
                [_json(source_metadata), result_id],
            )
            if team_names is None:
                for revision_id in source_lineage:
                    inherited_names = connection.execute(
                        "SELECT team_id, name FROM forecast_result.forecast_team_names "
                        "WHERE result_id = ? ORDER BY team_id",
                        [revision_id],
                    ).fetchall()
                    if inherited_names:
                        team_names = dict(inherited_names)
                        break
            if team_names:
                connection.executemany(
                    "INSERT INTO forecast_result.forecast_team_names VALUES (?, ?, ?)",
                    [(result_id, team_id, name) for team_id, name in sorted(team_names.items())],
                )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        connection.execute("CHECKPOINT")
    return {"result_id": result_id, "status": "written", "source_result_id": source_result_id}


def _insert_market_probabilities(
    connection,
    result_id: str,
    market_quotes: list[dict],
    market_pool: dict | None,
    structural_result_id: str,
) -> int:
    if market_pool is None:
        return 0
    selected = {}
    for quote in market_quotes:
        if quote["family"] != market_pool["market_family"]:
            continue
        if quote["match_id"] in selected:
            raise ValueError(f"Duplicate current market quote: {quote['match_id']}")
        selected[quote["match_id"]] = quote
    structural = connection.execute(
        """
        SELECT match_id, p_home, p_draw, p_away
        FROM forecast_result.forecast_match_probabilities
        WHERE result_id = ? AND stage = 'personnel_adjusted'
        """,
        [structural_result_id],
    ).fetchall()
    rows = []
    for match_id, p_home, p_draw, p_away in structural:
        quote = selected.get(match_id)
        if quote is None:
            continue
        values = market_assisted_probabilities((p_home, p_draw, p_away), quote, market_pool)
        rows.append(
            (
                result_id,
                match_id,
                "market_assisted",
                "personnel_adjusted",
                False,
                values["p_home"],
                values["p_draw"],
                values["p_away"],
                _json(values),
            )
        )
    if rows:
        connection.executemany(
            "INSERT INTO forecast_result.forecast_match_probabilities VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    return len(rows)


def _read_impacts(connection, result_id: str, impact_window: dict | None = None) -> dict | None:
    metadata = connection.execute(
        """
        SELECT simulations, horizon_days, window_start, window_end, coverage,
               minimum_conditional_samples, smallest_outcome_count, basis
        FROM forecast_result.forecast_impact_metadata WHERE result_id = ?
        """,
        [result_id],
    ).fetchone()
    if metadata is None:
        return None
    fixtures = []
    for row in connection.execute(
        """
        SELECT match_id, home_team_id, away_team_id, match_date, home_outcomes,
               draw_outcomes, away_outcomes, top_rms_movement
        FROM forecast_result.forecast_impact_fixtures WHERE result_id = ? ORDER BY match_id
        """,
        [result_id],
    ).fetchall():
        grouped = {}
        for values in connection.execute(
            """
            SELECT team_id, event, impact_order, outcome, baseline_probability, conditional_probability,
                   standard_error, rms_movement, swing, sufficient_sample
            FROM forecast_result.forecast_conditionals
            WHERE result_id = ? AND match_id = ? ORDER BY impact_order, outcome
            """,
            [result_id, row[0]],
        ).fetchall():
            key = values[0], values[1]
            impact = grouped.setdefault(
                key,
                {
                    "team_id": values[0],
                    "event": values[1],
                    "baseline": values[4],
                    "conditional": {},
                    "standard_error": {},
                    "rms_movement": values[7],
                    "swing": values[8],
                    "sufficient_sample": values[9],
                },
            )
            impact["conditional"][values[3]] = values[5]
            impact["standard_error"][values[3]] = values[6]
        fixtures.append(
            {
                "match_id": row[0],
                "home_team_id": row[1],
                "away_team_id": row[2],
                "match_date": _iso(row[3]),
                "outcome_counts": {"home": row[4], "draw": row[5], "away": row[6]},
                "top_rms_movement": row[7],
                "impacts": list(grouped.values()),
            }
        )
    impact_window = impact_window or {}
    return {
        "simulations": metadata[0],
        "horizon_days": metadata[1],
        "window_start": impact_window.get("window_start") or _iso(metadata[2]),
        "window_end": impact_window.get("window_end") or _iso(metadata[3]),
        "coverage": metadata[4],
        "minimum_conditional_samples": metadata[5],
        "smallest_outcome_count": metadata[6],
        "basis": metadata[7],
        "fixtures": fixtures,
    }
