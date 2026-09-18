import json
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import numpy as np

from epl_forecast.models import make_model
from epl_forecast.models.promotion import TeamPrior, completed_seasons
from epl_forecast.models.xg_observation import chance_rows
from epl_forecast.schema import Fixture, Match
from epl_forecast.storage import file_hash, json_bytes, sha256_bytes

SCHEMA_VERSION = 2
SOURCE_ROOT = Path(__file__).resolve().parent
FIT_PROTOCOL_PATHS = (
    SOURCE_ROOT / "models",
    SOURCE_ROOT / "competitions.py",
    SOURCE_ROOT / "datasets.py",
    SOURCE_ROOT / "schema.py",
    SOURCE_ROOT / "training.py",
    SOURCE_ROOT / "data" / "rules.py",
)


def fit_protocol_identity() -> str:
    paths = []
    for path in FIT_PROTOCOL_PATHS:
        paths.extend(sorted(path.rglob("*.py")) if path.is_dir() else [path])
    return sha256_bytes(
        json_bytes(
            {
                "schema_version": SCHEMA_VERSION,
                "files": {str(path.relative_to(SOURCE_ROOT)): file_hash(path) for path in paths},
            }
        )
    )


def _training_rows(matches: list[Match]) -> list[dict]:
    return [
        {
            "match_id": match.fixture.match_id,
            "competition_id": match.fixture.competition_id,
            "season_id": match.fixture.season_id,
            "match_date": match.fixture.match_date.isoformat(),
            "home_team_id": match.fixture.home_team_id,
            "away_team_id": match.fixture.away_team_id,
            "home_goals": match.home_goals,
            "away_goals": match.away_goals,
            "source_sha256": match.source_sha256,
            "source_row": match.source_row,
            "source_time": match.source_time,
        }
        for match in matches
    ]


def _ordered_training(matches: list[Match]) -> list[Match]:
    return sorted(matches, key=lambda match: (match.fixture.match_date, match.fixture.match_id))


def _observation_rows(matches: list[Match], observations) -> list[dict]:
    indexed = chance_rows(observations or ())
    rows = []
    for match in _ordered_training(matches):
        row = indexed.get(match.fixture.match_id)
        if row is None:
            continue
        day, available_on, home_goals, away_goals, home_xg, away_xg = row
        rows.append(
            {
                "match_id": match.fixture.match_id,
                "match_date": day.isoformat(),
                "available_on": available_on.isoformat(),
                "home_goals": home_goals,
                "away_goals": away_goals,
                "home_xg": home_xg,
                "away_xg": away_xg,
            }
        )
    return rows


def checkpoint_identity(
    spec: dict,
    training: list[Match],
    as_of: date,
    *,
    observations=None,
    protocol_identity: str | None = None,
) -> tuple[str, str, str, str, str]:
    training = _ordered_training(training)
    protocol_identity = protocol_identity or fit_protocol_identity()
    spec_sha256 = sha256_bytes(json_bytes(spec))
    training_sha256 = sha256_bytes(json_bytes(_training_rows(training)))
    observation_sha256 = sha256_bytes(json_bytes(_observation_rows(training, observations)))
    checkpoint_id = sha256_bytes(
        json_bytes(
            {
                "schema_version": SCHEMA_VERSION,
                "spec_sha256": spec_sha256,
                "training_sha256": training_sha256,
                "observation_sha256": observation_sha256,
                "protocol_identity": protocol_identity,
                "as_of": as_of.isoformat(),
            }
        )
    )
    return (
        checkpoint_id,
        spec_sha256,
        training_sha256,
        observation_sha256,
        protocol_identity,
    )


def _install_schema(connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS fit_checkpoints (
            checkpoint_id VARCHAR PRIMARY KEY,
            schema_version INTEGER NOT NULL,
            spec JSON NOT NULL,
            spec_sha256 VARCHAR NOT NULL,
            training_sha256 VARCHAR NOT NULL,
            input_revision VARCHAR NOT NULL,
            as_of DATE NOT NULL,
            competition_id VARCHAR NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            member_count INTEGER NOT NULL,
            prior_weights DOUBLE[] NOT NULL,
            weights DOUBLE[] NOT NULL,
            diagnostics JSON NOT NULL
        );
        CREATE TABLE IF NOT EXISTS fit_members (
            checkpoint_id VARCHAR NOT NULL,
            member_index INTEGER NOT NULL,
            as_of DATE NOT NULL,
            state_date DATE NOT NULL,
            competition_id VARCHAR NOT NULL,
            updates INTEGER NOT NULL,
            log_evidence DOUBLE NOT NULL,
            xg_updates INTEGER NOT NULL,
            mean DOUBLE[] NOT NULL,
            covariance DOUBLE[][] NOT NULL,
            diagnostics JSON NOT NULL,
            PRIMARY KEY (checkpoint_id, member_index)
        );
        CREATE TABLE IF NOT EXISTS fit_inputs (
            checkpoint_id VARCHAR PRIMARY KEY,
            observation_sha256 VARCHAR NOT NULL,
            protocol_identity VARCHAR NOT NULL
        );
        CREATE TABLE IF NOT EXISTS fit_teams (
            checkpoint_id VARCHAR NOT NULL,
            member_index INTEGER NOT NULL,
            team_id VARCHAR NOT NULL,
            team_index INTEGER NOT NULL,
            last_season VARCHAR NOT NULL,
            PRIMARY KEY (checkpoint_id, member_index, team_id)
        );
        CREATE TABLE IF NOT EXISTS fit_appearances (
            checkpoint_id VARCHAR NOT NULL,
            member_index INTEGER NOT NULL,
            team_id VARCHAR NOT NULL,
            season_id VARCHAR NOT NULL,
            appearances INTEGER NOT NULL,
            PRIMARY KEY (checkpoint_id, member_index, team_id, season_id)
        );
        CREATE TABLE IF NOT EXISTS fit_entry_priors (
            checkpoint_id VARCHAR NOT NULL,
            member_index INTEGER NOT NULL,
            team_id VARCHAR NOT NULL,
            season_id VARCHAR NOT NULL,
            mean DOUBLE[] NOT NULL,
            covariance DOUBLE[][] NOT NULL,
            source VARCHAR NOT NULL,
            PRIMARY KEY (checkpoint_id, member_index, team_id, season_id)
        );
        CREATE TABLE IF NOT EXISTS fit_history (
            checkpoint_id VARCHAR NOT NULL,
            match_order INTEGER NOT NULL,
            match_id VARCHAR NOT NULL,
            competition_id VARCHAR NOT NULL,
            season_id VARCHAR NOT NULL,
            match_date DATE NOT NULL,
            home_team_id VARCHAR NOT NULL,
            away_team_id VARCHAR NOT NULL,
            home_goals INTEGER NOT NULL,
            away_goals INTEGER NOT NULL,
            source_sha256 VARCHAR NOT NULL,
            source_row INTEGER NOT NULL,
            source_time VARCHAR NOT NULL,
            PRIMARY KEY (checkpoint_id, match_order)
        )
        """
    )


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def write_fit_checkpoint(
    path: Path,
    model,
    spec: dict,
    training: list[Match],
    as_of: date,
    input_revision: str,
    *,
    observations=None,
) -> str:
    training = _ordered_training(training)
    (
        checkpoint_id,
        spec_sha256,
        training_sha256,
        observation_sha256,
        protocol_identity,
    ) = checkpoint_identity(spec, training, as_of, observations=observations)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(path))
    try:
        _install_schema(connection)
        existing = connection.execute(
            "SELECT checkpoint_id FROM fit_checkpoints WHERE checkpoint_id = ?", [checkpoint_id]
        ).fetchone()
        if existing:
            return checkpoint_id
        members = list(getattr(model, "members", [model]))
        if any(member.as_of != as_of for member in members):
            raise ValueError("Every checkpoint member must be fitted at the requested cutoff")
        prior_weights = np.asarray(getattr(model, "prior_weights", [1.0]), dtype=float).tolist()
        weights = np.asarray(getattr(model, "weights", [1.0]), dtype=float).tolist()
        connection.execute("BEGIN")
        connection.execute(
            "INSERT INTO fit_checkpoints VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                checkpoint_id,
                SCHEMA_VERSION,
                _json(spec),
                spec_sha256,
                training_sha256,
                input_revision,
                as_of,
                members[0].competition_id,
                datetime.now(UTC),
                len(members),
                prior_weights,
                weights,
                _json(model.fit_diagnostics),
            ],
        )
        connection.execute(
            "INSERT INTO fit_inputs VALUES (?, ?, ?)",
            [checkpoint_id, observation_sha256, protocol_identity],
        )
        for member_index, member in enumerate(members):
            connection.execute(
                "INSERT INTO fit_members VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    checkpoint_id,
                    member_index,
                    member.as_of,
                    member._state_date,
                    member.competition_id,
                    member.updates,
                    float(getattr(member, "log_evidence", 0.0)),
                    int(getattr(member, "xg_updates", 0)),
                    member.mean.tolist(),
                    member.covariance.tolist(),
                    _json(member.fit_diagnostics),
                ],
            )
            connection.executemany(
                "INSERT INTO fit_teams VALUES (?, ?, ?, ?, ?)",
                [
                    [
                        checkpoint_id,
                        member_index,
                        team_id,
                        team_index,
                        member._last_season[team_id],
                    ]
                    for team_id, team_index in sorted(
                        member.team_index.items(), key=lambda row: row[1]
                    )
                ],
            )
            connection.executemany(
                "INSERT INTO fit_appearances VALUES (?, ?, ?, ?, ?)",
                [
                    [checkpoint_id, member_index, team_id, season_id, appearances]
                    for (team_id, season_id), appearances in sorted(member.appearances.items())
                ],
            )
            connection.executemany(
                "INSERT INTO fit_entry_priors VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    [
                        checkpoint_id,
                        member_index,
                        team_id,
                        season_id,
                        prior.mean.tolist(),
                        prior.covariance.tolist(),
                        prior.source,
                    ]
                    for (team_id, season_id), prior in sorted(member.entry_priors.items())
                ],
            )
        connection.executemany(
            "INSERT INTO fit_history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                [checkpoint_id, match_order, *row.values()]
                for match_order, row in enumerate(_training_rows(training))
            ],
        )
        connection.execute("COMMIT")
        connection.execute("CHECKPOINT")
    except Exception:
        try:
            connection.execute("ROLLBACK")
        except duckdb.TransactionException:
            pass
        raise
    finally:
        connection.close()
    return checkpoint_id


def _history(connection, checkpoint_id: str) -> list[Match]:
    rows = connection.execute(
        """
        SELECT match_id, competition_id, season_id, match_date, home_team_id, away_team_id,
               home_goals, away_goals, source_sha256, source_row, source_time
        FROM fit_history WHERE checkpoint_id = ? ORDER BY match_order
        """,
        [checkpoint_id],
    ).fetchall()
    return [Match(Fixture(*row[:6]), row[6], row[7], row[8], row[9], row[10]) for row in rows]


def load_fit_checkpoint(
    path: Path,
    spec: dict,
    training: list[Match],
    as_of: date,
    input_revision: str,
    *,
    observations=None,
):
    if not path.exists():
        return None
    training = _ordered_training(training)
    (
        checkpoint_id,
        spec_sha256,
        training_sha256,
        observation_sha256,
        protocol_identity,
    ) = checkpoint_identity(spec, training, as_of, observations=observations)
    connection = duckdb.connect(str(path), read_only=True)
    try:
        row = connection.execute(
            """
            SELECT schema_version, spec_sha256, training_sha256, input_revision, as_of,
                   competition_id, member_count, prior_weights, weights, diagnostics
            FROM fit_checkpoints WHERE checkpoint_id = ?
            """,
            [checkpoint_id],
        ).fetchone()
        if row is None:
            return None
        stored_input = connection.execute(
            "SELECT observation_sha256, protocol_identity FROM fit_inputs WHERE checkpoint_id = ?",
            [checkpoint_id],
        ).fetchone()
        if row[:3] != (SCHEMA_VERSION, spec_sha256, training_sha256) or row[4] != as_of:
            raise ValueError("Fit checkpoint identity does not match its metadata")
        if stored_input != (observation_sha256, protocol_identity):
            raise ValueError("Fit checkpoint inputs do not match its identity")
        history = _history(connection, checkpoint_id)
        if history != training:
            raise ValueError("Fit checkpoint history does not match the requested training set")
        model = make_model(spec, observations=observations)
        members = list(getattr(model, "members", [model]))
        if len(members) != row[6]:
            raise ValueError("Fit checkpoint member count does not match the model")
        member_rows = connection.execute(
            """
            SELECT member_index, as_of, state_date, competition_id, updates, log_evidence,
                   xg_updates, mean, covariance, diagnostics
            FROM fit_members WHERE checkpoint_id = ? ORDER BY member_index
            """,
            [checkpoint_id],
        ).fetchall()
        if len(member_rows) != len(members):
            raise ValueError("Fit checkpoint has incomplete member state")
        for member, member_row in zip(members, member_rows, strict=True):
            member_index = member_row[0]
            member.as_of = member_row[1]
            member._state_date = member_row[2]
            member.competition_id = member_row[3]
            member.updates = member_row[4]
            member.log_evidence = member_row[5]
            member.xg_updates = member_row[6]
            member.mean = np.asarray(member_row[7], dtype=float)
            member.covariance = np.asarray(member_row[8], dtype=float)
            member.fit_diagnostics = json.loads(member_row[9])
            team_rows = connection.execute(
                """
                SELECT team_id, team_index, last_season FROM fit_teams
                WHERE checkpoint_id = ? AND member_index = ? ORDER BY team_index
                """,
                [checkpoint_id, member_index],
            ).fetchall()
            member.team_index = {team_id: team_index for team_id, team_index, _ in team_rows}
            member._last_season = {team_id: season for team_id, _, season in team_rows}
            member.appearances = Counter(
                {
                    (team_id, season_id): appearances
                    for team_id, season_id, appearances in connection.execute(
                        """
                        SELECT team_id, season_id, appearances FROM fit_appearances
                        WHERE checkpoint_id = ? AND member_index = ?
                        """,
                        [checkpoint_id, member_index],
                    ).fetchall()
                }
            )
            member.entry_priors = {
                (team_id, season_id): TeamPrior(
                    np.asarray(mean, dtype=float), np.asarray(covariance, dtype=float), source
                )
                for team_id, season_id, mean, covariance, source in connection.execute(
                    """
                    SELECT team_id, season_id, mean, covariance, source FROM fit_entry_priors
                    WHERE checkpoint_id = ? AND member_index = ?
                    """,
                    [checkpoint_id, member_index],
                ).fetchall()
            }
            member._history = history.copy()
            member._seasons = completed_seasons(history, as_of)
            member._bridges = {}
            member._entry_models = {}
        model.as_of = as_of
        model.team_index = members[0].team_index
        model.prior_weights = np.asarray(row[7], dtype=float)
        model.weights = np.asarray(row[8], dtype=float)
        model.fit_diagnostics = json.loads(row[9])
        return model
    finally:
        connection.close()


def _resume_fit_checkpoint(
    path: Path,
    spec: dict,
    training: list[Match],
    as_of: date,
    *,
    observations=None,
):
    if not path.exists():
        return None
    training = _ordered_training(training)
    _, spec_sha256, _, _, _ = checkpoint_identity(spec, training, as_of, observations=observations)
    competition_id = spec.get("parameters", {}).get("competition_id", "eng-premier-league")
    connection = duckdb.connect(str(path), read_only=True)
    try:
        candidates = connection.execute(
            """
            SELECT checkpoint_id, as_of, input_revision
            FROM fit_checkpoints
            WHERE schema_version = ? AND spec_sha256 = ? AND competition_id = ? AND as_of <= ?
            ORDER BY as_of DESC, created_at DESC
            """,
            [SCHEMA_VERSION, spec_sha256, competition_id, as_of],
        ).fetchall()
        histories = [
            (checkpoint_id, checkpoint_as_of, input_revision, _history(connection, checkpoint_id))
            for checkpoint_id, checkpoint_as_of, input_revision in candidates
        ]
    finally:
        connection.close()
    for _, checkpoint_as_of, input_revision, history in histories:
        if len(history) > len(training) or training[: len(history)] != history:
            continue
        if (
            len(history) < len(training)
            and history[-1].fixture.match_date == training[len(history)].fixture.match_date
        ):
            continue
        model = load_fit_checkpoint(
            path,
            spec,
            history,
            checkpoint_as_of,
            input_revision,
            observations=observations,
        )
        if model is None:
            continue
        model.fit(training, as_of)
        return model
    return None


def fitted_model_from_checkpoint(
    path: Path,
    spec: dict,
    training: list[Match],
    as_of: date,
    input_revision: str,
    *,
    observations=None,
):
    model = load_fit_checkpoint(
        path,
        spec,
        training,
        as_of,
        input_revision,
        observations=observations,
    )
    if model is not None:
        model.fit_state_status = "exact"
        return model, True
    model = _resume_fit_checkpoint(path, spec, training, as_of, observations=observations)
    if model is None:
        model = make_model(spec, observations=observations).fit(training, as_of)
        model.fit_state_status = "fresh"
    else:
        model.fit_state_status = "resumed"
    write_fit_checkpoint(
        path,
        model,
        spec,
        training,
        as_of,
        input_revision,
        observations=observations,
    )
    return model, False
