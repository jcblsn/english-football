"""A reproducible DuckDB session for canonical and derived product evidence."""

import hashlib
import json
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

from epl_forecast import analysis_contract
from epl_forecast.datasets import Dataset
from epl_forecast.storage import R2Store, json_bytes


class CachedArtifactStore:
    """Cache immutable JSON artifacts while leaving mutable indexes authoritative."""

    def __init__(self, store, root: Path, namespace: str):
        self.store = store
        self.root = root / namespace

    def configure_duckdb(self, connection, name="page324_r2") -> None:
        self.store.configure_duckdb(connection, name=name)

    def uri(self, key: str) -> str:
        return self.store.uri(key)

    def get_json(self, key: str, default=None):
        if not self._immutable(key):
            return self.store.get_json(key, default)
        path = self.root / key
        try:
            return json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            value = self.store.get_json(key, default)
            if value is default:
                return default
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_bytes(json_bytes(value))
            temporary.replace(path)
            return value

    def _immutable(self, key: str) -> bool:
        if key.startswith("runs/forecasts/"):
            return key.endswith(("/forecast.json", "/run.json"))
        if key.startswith("runs/hindcasts/"):
            return key.endswith(".json") and not key.endswith(("/series.json", "/edition.json"))
        if key.startswith("forecasts/"):
            return key.endswith(".json") and not key.endswith(("/archive.json", "/current.json"))
        if key.startswith("hindcasts/"):
            return key.endswith(".json") and not key.endswith(("/index.json", "/series.json"))
        return False


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
        True,
        "Derived artifacts keep their own timing fields.",
    ),
    (
        "catalog",
        "one row per analysis object",
        "Grain, meaning, source, timing, visibility, and caveats for each analysis object.",
        "analysis bootstrap",
        "Descriptive metadata, not event time.",
        True,
        None,
    ),
    (
        "matches",
        "one row per match_id",
        "Cross-provider reconciled fixtures with contradiction checks.",
        "Dataset.fixtures()",
        "Canonical rows retrieved by the session evidence cutoff.",
        True,
        "This is not the raw SQL fixtures view, which is latest per provider.",
    ),
    (
        "team_matches",
        "two rows per match_id",
        "Team-oriented match results and opponent context.",
        "analysis.matches",
        "Inherits the canonical evidence cutoff.",
        True,
        None,
    ),
    (
        "team_match_xg",
        "one row per match with preferred xG for both teams",
        "Model-observed xG under the API-Football and Understat transition policy.",
        "Dataset.xg_observations()",
        "Inherits the canonical evidence cutoff and model availability rule.",
        True,
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
    (
        "forecasts",
        "one row per successful forecast and competition",
        "Successful live forecast identity, timing, model, simulation, and storage provenance.",
        "competition forecast archive pointers, public document, and private run",
        "generated_at, state_observed_at, and model_results_cutoff have distinct meanings.",
        False,
        "A row exists only when both the successful public document and expected private run exist.",
    ),
    (
        "forecast_matches",
        "one row per successful forecast and modeled match",
        "Complete private match predictions with explicit public horizon membership.",
        "private forecast.json enriched by its public forecast",
        "The forecast timing fields are in analysis.forecasts.",
        True,
        "Structural and market-assisted probabilities are separate. Season simulations use structural probabilities.",
    ),
    (
        "forecast_teams",
        "one row per successful forecast and team",
        "Scalar live season estimates.",
        "successful public forecast teams",
        "The forecast timing fields are in analysis.forecasts.",
        False,
        None,
    ),
    (
        "forecast_team_events",
        "one row per forecast, team, and event",
        "Division-specific live event probabilities.",
        "successful public forecast teams.events",
        "The forecast timing fields are in analysis.forecasts.",
        False,
        None,
    ),
    (
        "forecast_points_distribution",
        "one row per forecast, team, and points total",
        "Live points distributions.",
        "successful public forecast teams.points_distribution",
        "The forecast timing fields are in analysis.forecasts.",
        False,
        None,
    ),
    (
        "forecast_position_distribution",
        "one row per forecast, team, and final position",
        "Live position distributions.",
        "successful public forecast teams.position_probabilities",
        "The forecast timing fields are in analysis.forecasts.",
        False,
        None,
    ),
    (
        "forecast_intervals",
        "one row per forecast, team, estimate, and interval level",
        "Live points and position intervals.",
        "successful public forecast team interval maps",
        "The forecast timing fields are in analysis.forecasts.",
        False,
        None,
    ),
    (
        "model_team_states",
        "one row per forecast and team",
        "Private model team state with stable common fields and the complete state as JSON.",
        "private forecast.json team_strengths",
        "State used by this forecast run.",
        True,
        None,
    ),
    (
        "forecast_runs",
        "one row per successful forecast and competition",
        "Private run provenance and fit diagnostics.",
        "private run.json and forecast.json",
        "Run creation time is analysis.forecasts.generated_at.",
        True,
        "Complex diagnostics and provenance remain JSON.",
    ),
    (
        "forecast_impacts",
        "one row per forecast, match, event, team, and outcome",
        "Conditional match impact values and carry-forward provenance.",
        "successful public forecast impact surface",
        "Carry-forward fields identify the last eligible pre-kickoff forecast.",
        False,
        None,
    ),
    (
        "hindcast_origins",
        "one row per retrospective hindcast origin",
        "Retrospective season estimate identity and timing.",
        "hindcast index, series pointers, public document, and private run",
        "origin_at is a retrospective simulation origin, not an artifact creation time.",
        False,
        "retrospective is always true and generated_at is intentionally null.",
    ),
    (
        "hindcast_teams",
        "one row per hindcast origin and team",
        "Scalar retrospective season estimates.",
        "successful public hindcast documents",
        "Join hindcast_origins for explicit retrospective timing.",
        False,
        None,
    ),
    (
        "hindcast_team_events",
        "one row per hindcast origin, team, and event",
        "Division-specific retrospective event probabilities.",
        "successful public hindcast documents",
        "Join hindcast_origins for explicit retrospective timing.",
        False,
        None,
    ),
    (
        "hindcast_points_distribution",
        "one row per hindcast origin, team, and points total",
        "Retrospective points distributions.",
        "successful public hindcast documents",
        "Join hindcast_origins for explicit retrospective timing.",
        False,
        None,
    ),
    (
        "hindcast_position_distribution",
        "one row per hindcast origin, team, and final position",
        "Retrospective position distributions.",
        "successful public hindcast documents",
        "Join hindcast_origins for explicit retrospective timing.",
        False,
        None,
    ),
    (
        "hindcast_intervals",
        "one row per hindcast origin, team, estimate, and interval level",
        "Retrospective points and position intervals.",
        "successful public hindcast documents",
        "Join hindcast_origins for explicit retrospective timing.",
        False,
        None,
    ),
    (
        "record_matches",
        "one row per pending or settled prospective match forecast",
        "Last pre-kickoff forecast and realized outcome from the prospective record.",
        "record.json",
        "generated_at is the actual live forecast time.",
        False,
        None,
    ),
    (
        "record_summary",
        "one row per scoring scope",
        "Prospective scoring summary, with complete metrics as JSON.",
        "record.json summary",
        "Summarizes settled prospective forecasts only.",
        False,
        None,
    ),
    (
        "team_projections",
        "one row per live forecast or hindcast origin and team",
        "Convenience union of scalar live and retrospective team estimates.",
        "analysis.forecast_teams and analysis.hindcast_teams",
        "Use product, retrospective, generated_at, origin_at, state_observed_at, and model_results_cutoff together.",
        False,
        "There is no generic as-of timestamp across products.",
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


def _install_canonical_analysis(data: Dataset, cache: Path | None = None) -> None:
    connection = data.con
    connection.execute("CREATE SCHEMA analysis")
    fingerprint = hashlib.sha256(
        json_bytes(
            {
                "analysis_schema_version": analysis_contract.ANALYSIS_SCHEMA_VERSION,
                "manifests": data.manifests,
                "cutoff": data.cutoff.isoformat() if data.cutoff else None,
            }
        )
    ).hexdigest()
    if cache is not None:
        try:
            pointer = json.loads((cache / "current.json").read_text())
            directory = cache / "sessions" / pointer["fingerprint"]
            if (
                pointer.get("analysis_schema_version") == analysis_contract.ANALYSIS_SCHEMA_VERSION
                and pointer["fingerprint"] == fingerprint
            ):
                connection.execute(
                    "CREATE TABLE analysis.matches AS SELECT * FROM read_parquet(?)",
                    [str(directory / "matches.parquet")],
                )
                connection.execute(
                    "CREATE TABLE analysis.team_match_xg AS SELECT * FROM read_parquet(?)",
                    [str(directory / "team_match_xg.parquet")],
                )
                _install_canonical_views(connection)
                return
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            connection.execute("DROP TABLE IF EXISTS analysis.matches")
            connection.execute("DROP TABLE IF EXISTS analysis.team_match_xg")
    connection.execute("CREATE TABLE analysis.matches AS SELECT * FROM fixtures LIMIT 0")
    matches = data.fixtures()
    if matches:
        columns = [row[0] for row in connection.execute("DESCRIBE analysis.matches").fetchall()]
        schema = json.dumps(
            [
                {
                    row[1]: row[2]
                    for row in connection.execute(
                        "PRAGMA table_info('analysis.matches')"
                    ).fetchall()
                }
            ]
        )
        for start in range(0, len(matches), 10_000):
            payload = [
                {column: row[column] for column in columns}
                for row in matches[start : start + 10_000]
            ]
            connection.execute(
                "INSERT INTO analysis.matches BY NAME "
                "SELECT unnest(from_json_strict(?, ?), recursive := true)",
                [json.dumps(payload, default=str, allow_nan=False), schema],
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
    _install_canonical_views(connection)
    if cache is not None:
        sessions = cache / "sessions"
        target = sessions / fingerprint
        temporary = sessions / f".{fingerprint}.tmp"
        if not target.exists():
            shutil.rmtree(temporary, ignore_errors=True)
            temporary.mkdir(parents=True)
            for table in ("matches", "team_match_xg"):
                connection.execute(
                    f"COPY analysis.{table} TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
                    [str(temporary / f"{table}.parquet")],
                )
            temporary.replace(target)
        old = None
        try:
            old = json.loads((cache / "current.json").read_text()).get("fingerprint")
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        cache.mkdir(parents=True, exist_ok=True)
        pointer = cache / "current.tmp"
        pointer.write_bytes(
            json_bytes(
                {
                    "analysis_schema_version": analysis_contract.ANALYSIS_SCHEMA_VERSION,
                    "fingerprint": fingerprint,
                }
            )
        )
        pointer.replace(cache / "current.json")
        if old and old != fingerprint:
            shutil.rmtree(sessions / old, ignore_errors=True)


def _install_canonical_views(connection) -> None:
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
         AND a.scope LIKE 'fixture:%'
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


def _install_metadata(
    data: Dataset,
    loaded_at: datetime,
    publication_index_timestamps: dict | None = None,
    model_versions: set[str] | None = None,
) -> None:
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
            ("analysis_schema_version", "INTEGER"),
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
                "analysis_schema_version": analysis_contract.ANALYSIS_SCHEMA_VERSION,
                "evidence_cutoff": data.cutoff,
                "remote_only": True,
                "manifest_identity_sha256": identity,
                "manifest_batches": _json([row["batch_id"] for row in manifests]),
                "canonical_catalog_schema_version": catalog_state.get("schema_version"),
                "publication_index_timestamps": _json(publication_index_timestamps or {}),
                "loaded_model_versions": _json(sorted(model_versions or set())),
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
    cache: Path | None = Path("runs/analysis-cache"),
) -> AnalysisSession:
    """Open the authoritative remote corpus and install its analytical namespace."""
    data_store = data_store or R2Store.from_environment("R2_DATA_BUCKET")
    if include_derived:
        publish_store = publish_store or R2Store.from_environment("R2_PUBLISH_BUCKET")
    normalized_cache = (
        cache / "normalized"
        if cache is not None
        and isinstance(data_store, R2Store)
        and isinstance(publish_store, R2Store)
        else None
    )
    canonical_cache = cache / "canonical" if normalized_cache is not None else None
    if cache is not None and isinstance(data_store, R2Store):
        data_store = CachedArtifactStore(data_store, cache, "data")
    if cache is not None and isinstance(publish_store, R2Store):
        publish_store = CachedArtifactStore(publish_store, cache, "publication")
    dataset = Dataset(root, cutoff, store=data_store, include_local=False)
    try:
        if include_derived:
            publish_store.configure_duckdb(dataset.con, name="page324_publish")
        _install_canonical_analysis(dataset, canonical_cache)
        publication_index_timestamps = {}
        model_versions = set()
        if include_derived:
            from epl_forecast.analysis_artifacts import install_artifact_analysis

            publication_index_timestamps, model_versions = install_artifact_analysis(
                dataset.con, data_store, publish_store, normalized_cache
            )
        _install_metadata(dataset, datetime.now(UTC), publication_index_timestamps, model_versions)
        return AnalysisSession(dataset, publish_store)
    except Exception:
        dataset.close()
        raise


def start_ui(session: AnalysisSession, *, open_browser: bool = True) -> str:
    """Start the DuckDB UI for a prepared connection and wait until interruption."""
    procedure = "start_ui" if open_browser else "start_ui_server"
    row = session.connection.execute(f"CALL {procedure}()").fetchone()
    url = str(row[0]) if row and isinstance(row[0], str) else "http://localhost:4213"
    print(f"DuckDB UI: {url}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return url
    finally:
        session.connection.execute("CALL stop_ui_server()")
