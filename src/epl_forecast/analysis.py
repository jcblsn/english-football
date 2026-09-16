"""A reproducible DuckDB session for canonical and derived product evidence."""

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from epl_forecast.datasets import Dataset
from epl_forecast.storage import R2Store, json_bytes


def _ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _json(value) -> str | None:
    return None if value is None else json.dumps(value, sort_keys=True, allow_nan=False)


def _create_table(connection, name: str, columns: tuple[tuple[str, str], ...], rows=()) -> None:
    definition = ", ".join(f"{_ident(column)} {kind}" for column, kind in columns)
    connection.execute(f"CREATE TABLE {name} ({definition})")
    names = [column for column, _ in columns]
    values = [tuple(row.get(column) for column in names) for row in rows]
    if values:
        placeholders = ", ".join("?" for _ in names)
        connection.executemany(f"INSERT INTO {name} VALUES ({placeholders})", values)


CATALOG_ROWS = (
    (
        "session",
        "one row per analysis session",
        "Reproducibility metadata for the canonical and publication corpus loaded in this connection.",
        "canonical manifest state and publication indexes",
        "The evidence cutoff applies to canonical rows only.",
        False,
        "Derived artifacts keep their own timing fields.",
    ),
    (
        "catalog",
        "one row per analysis object",
        "Grain, meaning, source, timing, visibility, and caveats for each analysis object.",
        "analysis bootstrap",
        "Descriptive metadata, not event time.",
        False,
        None,
    ),
    (
        "matches",
        "one row per match_id",
        "Cross-provider reconciled fixtures with contradiction checks.",
        "Dataset.fixtures()",
        "Canonical rows retrieved by the session evidence cutoff.",
        False,
        "This is not the raw SQL fixtures view, which is latest per provider.",
    ),
    (
        "team_matches",
        "two rows per match_id",
        "Team-oriented match results and opponent context.",
        "analysis.matches",
        "Inherits the canonical evidence cutoff.",
        False,
        None,
    ),
    (
        "team_match_xg",
        "one row per match with preferred xG for both teams",
        "Model-observed xG under the API-Football and Understat transition policy.",
        "Dataset.xg_observations()",
        "Inherits the canonical evidence cutoff and model availability rule.",
        False,
        None,
    ),
    (
        "player_matches",
        "one row per match, player, and team in the selected provider capture",
        "Player appearances with reconciled match and player names.",
        "canonical appearances, players, and analysis.matches",
        "Canonical rows retrieved by the session evidence cutoff.",
        True,
        "Repeated captures remain visible. Use retrieved_at and source_sha256 when selecting one response.",
    ),
    (
        "personnel_snapshots",
        "one row per successful query scope",
        "Latest successful response identity, including responses with no rows.",
        "canonical source_snapshots",
        "Latest (retrieved_at, source_sha256) at the session cutoff.",
        True,
        None,
    ),
    (
        "squad_memberships",
        "one row per latest squad snapshot and reported player, or one null-player row when empty",
        "Snapshot-safe captured squad membership.",
        "canonical memberships and source_snapshots",
        "Latest successful team_squad response at the session cutoff.",
        True,
        "A null player_id with row_count=0 is a meaningful empty response.",
    ),
    (
        "injury_availability",
        "one row per latest injury snapshot and reported player, or one null-player row when empty",
        "Snapshot-safe competition injury evidence.",
        "canonical availability and source_snapshots",
        "Latest successful competition_injuries response at the session cutoff.",
        True,
        "Absence is not proof of availability outside the covered snapshot.",
    ),
    (
        "fpl_availability",
        "one row per latest FPL snapshot and reported player, or one null-player row when empty",
        "Snapshot-safe FPL availability evidence.",
        "canonical availability and source_snapshots",
        "Latest successful fpl_availability response at the session cutoff.",
        True,
        "A null player_id with row_count=0 is a meaningful empty response.",
    ),
)


class AnalysisSession:
    """A prepared analytical connection and the resources that own it."""

    def __init__(self, dataset: Dataset, publish_store=None):
        self.dataset = dataset
        self.publish_store = publish_store
        self.connection = dataset.con

    def close(self) -> None:
        self.dataset.close()

    def rows(self, sql: str, parameters=None) -> list[dict]:
        return self.dataset.rows(sql, parameters)


def _install_canonical_analysis(data: Dataset) -> None:
    connection = data.con
    connection.execute("CREATE SCHEMA analysis")
    connection.execute("CREATE TABLE analysis.matches AS SELECT * FROM fixtures LIMIT 0")
    matches = data.fixtures()
    if matches:
        columns = [row[0] for row in connection.execute("DESCRIBE analysis.matches").fetchall()]
        placeholders = ", ".join("?" for _ in columns)
        connection.executemany(
            f"INSERT INTO analysis.matches VALUES ({placeholders})",
            [tuple(row[column] for column in columns) for row in matches],
        )
    xg = data.xg_observations()
    _create_table(
        connection,
        "analysis.team_match_xg",
        (
            ("match_id", "VARCHAR PRIMARY KEY"),
            ("season_id", "VARCHAR"),
            ("match_date", "VARCHAR"),
            ("home_team_id", "VARCHAR"),
            ("away_team_id", "VARCHAR"),
            ("home_goals", "INTEGER"),
            ("away_goals", "INTEGER"),
            ("home_xg", "DOUBLE"),
            ("away_xg", "DOUBLE"),
            ("source_sha256", "VARCHAR"),
            ("available_on", "VARCHAR"),
            ("availability_basis", "VARCHAR"),
        ),
        xg,
    )
    connection.execute(
        """
        CREATE VIEW analysis.team_matches AS
        SELECT match_id, competition_id, season_id, match_date, kickoff_time,
               home_team_id AS team_id, away_team_id AS opponent_id, 'home' AS venue,
               home_goals AS goals_for, away_goals AS goals_against,
               CASE WHEN status <> 'finished' THEN NULL
                    WHEN home_goals > away_goals THEN 'W'
                    WHEN home_goals = away_goals THEN 'D' ELSE 'L' END AS result,
               status, stage
        FROM analysis.matches
        UNION ALL
        SELECT match_id, competition_id, season_id, match_date, kickoff_time,
               away_team_id AS team_id, home_team_id AS opponent_id, 'away' AS venue,
               away_goals AS goals_for, home_goals AS goals_against,
               CASE WHEN status <> 'finished' THEN NULL
                    WHEN away_goals > home_goals THEN 'W'
                    WHEN away_goals = home_goals THEN 'D' ELSE 'L' END AS result,
               status, stage
        FROM analysis.matches
        """
    )
    connection.execute(
        """
        CREATE VIEW analysis.player_matches AS
        SELECT a.*, p.name AS player_name, m.match_date, m.status AS match_status,
               m.home_team_id, m.away_team_id
        FROM appearances_observations a
        LEFT JOIN players p USING (player_id)
        LEFT JOIN analysis.matches m USING (match_id)
        """
    )
    connection.execute(
        """
        CREATE VIEW analysis.personnel_snapshots AS
        SELECT * FROM source_snapshots_observations
        QUALIFY row_number() OVER (
            PARTITION BY scope_kind, scope_key
            ORDER BY retrieved_at DESC, source_sha256 DESC
        ) = 1
        """
    )
    connection.execute(
        """
        CREATE VIEW analysis.squad_memberships AS
        SELECT s.scope_key AS team_id, s.row_count, s.retrieved_at, s.source_sha256,
               m.player_id, p.name AS player_name, m.season_id, m.competition_id,
               m.position, m.basis
        FROM analysis.personnel_snapshots s
        LEFT JOIN memberships_observations m
          ON s.scope_kind = 'team_squad'
         AND m.team_id = s.scope_key
         AND m.basis = 'captured_squad'
         AND m.retrieved_at = s.retrieved_at
         AND m.source_sha256 = s.source_sha256
        LEFT JOIN players p USING (player_id)
        WHERE s.scope_kind = 'team_squad'
        """
    )
    connection.execute(
        """
        CREATE VIEW analysis.injury_availability AS
        SELECT s.scope_key, s.row_count, s.retrieved_at, s.source_sha256,
               a.player_id, p.name AS player_name, a.team_id, a.competition_id,
               a.season_id, a.match_id, a.status, a.reason, a.start_date, a.end_date
        FROM analysis.personnel_snapshots s
        LEFT JOIN availability_observations a
          ON s.scope_kind = 'competition_injuries'
         AND a.provider = 'api_football'
         AND a.competition_id = s.competition_id
         AND a.season_id = s.season_id
         AND a.retrieved_at = s.retrieved_at
         AND a.source_sha256 = s.source_sha256
        LEFT JOIN players p USING (player_id)
        WHERE s.scope_kind = 'competition_injuries'
        """
    )
    connection.execute(
        """
        CREATE VIEW analysis.fpl_availability AS
        SELECT s.scope_key AS season_id, s.row_count, s.retrieved_at, s.source_sha256,
               a.player_id, p.name AS player_name, a.team_id, a.status, a.reason,
               a.chance_this_round, a.chance_next_round, a.current_round, a.next_round,
               a.news_added
        FROM analysis.personnel_snapshots s
        LEFT JOIN availability_observations a
          ON s.scope_kind = 'fpl_availability'
         AND a.provider = 'fpl'
         AND a.season_id = s.scope_key
         AND a.retrieved_at = s.retrieved_at
         AND a.source_sha256 = s.source_sha256
        LEFT JOIN players p USING (player_id)
        WHERE s.scope_kind = 'fpl_availability'
        """
    )


def _install_metadata(data: Dataset, loaded_at: datetime) -> None:
    connection = data.con
    catalog = [
        {
            "object_name": row[0],
            "grain": row[1],
            "meaning": row[2],
            "source": row[3],
            "temporal_semantics": row[4],
            "private": row[5],
            "caveats": row[6],
        }
        for row in CATALOG_ROWS
    ]
    _create_table(
        connection,
        "analysis.catalog",
        (
            ("object_name", "VARCHAR PRIMARY KEY"),
            ("grain", "VARCHAR"),
            ("meaning", "VARCHAR"),
            ("source", "VARCHAR"),
            ("temporal_semantics", "VARCHAR"),
            ("private", "BOOLEAN"),
            ("caveats", "VARCHAR"),
        ),
        catalog,
    )
    manifests = data.manifests
    identity = hashlib.sha256(json_bytes(manifests)).hexdigest()
    catalog_state = data.store.get_json("state/manifests.json", {}) if data.store else {}
    _create_table(
        connection,
        "analysis.session",
        (
            ("loaded_at", "TIMESTAMPTZ"),
            ("evidence_cutoff", "TIMESTAMPTZ"),
            ("remote_only", "BOOLEAN"),
            ("manifest_identity_sha256", "VARCHAR"),
            ("manifest_batches", "JSON"),
            ("canonical_catalog_schema_version", "INTEGER"),
            ("publication_index_timestamps", "JSON"),
            ("loaded_model_versions", "JSON"),
        ),
        (
            {
                "loaded_at": loaded_at,
                "evidence_cutoff": data.cutoff,
                "remote_only": True,
                "manifest_identity_sha256": identity,
                "manifest_batches": _json([row["batch_id"] for row in manifests]),
                "canonical_catalog_schema_version": catalog_state.get("schema_version"),
                "publication_index_timestamps": _json({}),
                "loaded_model_versions": _json([]),
            },
        ),
    )


def open_analysis_session(
    cutoff=None,
    *,
    data_store=None,
    publish_store=None,
    root: Path = Path("data"),
    include_derived: bool = True,
) -> AnalysisSession:
    """Open the authoritative remote corpus and install its analytical namespace."""
    data_store = data_store or R2Store.from_environment("R2_DATA_BUCKET")
    if include_derived:
        publish_store = publish_store or R2Store.from_environment("R2_PUBLISH_BUCKET")
    dataset = Dataset(root, cutoff, store=data_store, include_local=False)
    try:
        _install_canonical_analysis(dataset)
        _install_metadata(dataset, datetime.now(UTC))
        return AnalysisSession(dataset, publish_store)
    except Exception:
        dataset.close()
        raise


def start_ui(session: AnalysisSession, *, open_browser: bool = True) -> str:
    """Start the DuckDB UI for a prepared connection and wait until interruption."""
    procedure = "start_ui" if open_browser else "start_ui_server"
    row = session.connection.execute(f"CALL {procedure}()").fetchone()
    url = str(row[0]) if row else ""
    print(f"DuckDB UI: {url}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return url
