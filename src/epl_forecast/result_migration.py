"""One-way migration from score-cell result stores to compact score-grid stores."""

from pathlib import Path

import duckdb

from epl_forecast.datasets import SESSION_TIME_ZONE
from epl_forecast.results import (
    RESULT_SCHEMA_VERSION,
    _decoded,
    _store_run_provenance,
    install_result_schema,
)

COPIED_TABLES = (
    "forecast_public_documents",
    "forecast_matches",
    "forecast_team_names",
    "forecast_unsettled_fixtures",
    "forecast_match_probabilities",
    "forecast_team_seasons",
    "forecast_team_events",
    "forecast_team_points",
    "forecast_team_positions",
    "forecast_team_strengths",
    "forecast_conditionals",
    "forecast_impact_metadata",
    "forecast_impact_fixtures",
)
RUN_COLUMNS = (
    "result_id",
    "competition_id",
    "season_id",
    "state_observed_at",
    "model_results_cutoff",
    "generated_at",
    "model_id",
    "model_kind",
    "input_revision",
    "model_spec",
    "simulation_settings",
    "simulation_metadata",
    "software_provenance",
    "fit_diagnostics",
    "source_document_sha256",
    "schema_version",
    "stored_at",
    "forecast_metadata",
    "source_result_id",
    "market_replacement",
)


def migrate_result_database(source: Path, destination: Path) -> dict[str, int]:
    """Create one compact database from one immutable legacy result database."""
    source, destination = Path(source), Path(destination)
    if not source.is_file():
        raise FileNotFoundError(source)
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with duckdb.connect(str(destination)) as connection:
            connection.execute(SESSION_TIME_ZONE)
            install_result_schema(connection)
            source_sql = str(source).replace("'", "''")
            connection.execute(f"ATTACH '{source_sql}' AS legacy (READ_ONLY)")
            connection.execute("BEGIN TRANSACTION")
            try:
                source_columns = [
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info('legacy.forecast_result.forecast_runs')"
                    ).fetchall()
                ]
                runs = connection.execute(
                    "SELECT * FROM legacy.forecast_result.forecast_runs ORDER BY result_id"
                ).fetchall()
                for source_row in runs:
                    source_values = dict(zip(source_columns, source_row, strict=True))
                    row = [
                        source_values.get(column, False if column == "market_replacement" else None)
                        for column in RUN_COLUMNS
                    ]
                    row[12] = _store_run_provenance(connection, row[0], _decoded(row[12]) or {})
                    row[15] = RESULT_SCHEMA_VERSION
                    connection.execute(
                        "INSERT INTO forecast_result.forecast_runs VALUES "
                        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        row,
                    )
                for table in COPIED_TABLES:
                    connection.execute(
                        f"INSERT INTO forecast_result.{table} "
                        f"SELECT * FROM legacy.forecast_result.{table}"
                    )
                connection.execute(
                    """
                    INSERT INTO forecast_result.forecast_score_grids
                    SELECT score.result_id, score.match_id, score.stage,
                           CAST(max(score.home_goals) + 1 AS USMALLINT),
                           CAST(max(score.away_goals) + 1 AS USMALLINT),
                           list(score.probability ORDER BY score.home_goals, score.away_goals)::DOUBLE[],
                           any_value(metadata.home_rate), any_value(metadata.away_rate),
                           any_value(metadata.omitted_probability),
                           any_value(metadata.uncertainty_components)
                    FROM legacy.forecast_result.forecast_scores AS score
                    JOIN legacy.forecast_result.forecast_score_metadata AS metadata
                    USING (result_id, match_id, stage)
                    GROUP BY score.result_id, score.match_id, score.stage
                    """
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
            connection.execute("CHECKPOINT")
            counts = {
                "results": connection.execute(
                    "SELECT count(*) FROM forecast_result.forecast_runs"
                ).fetchone()[0],
                "grids": connection.execute(
                    "SELECT count(*) FROM forecast_result.forecast_score_grids"
                ).fetchone()[0],
                "cells": connection.execute(
                    "SELECT coalesce(sum(array_length(probabilities)), 0) "
                    "FROM forecast_result.forecast_score_grids"
                ).fetchone()[0],
                "provenance_documents": connection.execute(
                    "SELECT count(*) FROM forecast_result.forecast_documents"
                ).fetchone()[0],
            }
        return counts
    except Exception:
        destination.unlink(missing_ok=True)
        raise
