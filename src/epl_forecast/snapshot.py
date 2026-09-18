"""Create and restore one verified local database revision."""

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import duckdb

from epl_forecast.datasets import (
    SCHEMAS,
    SESSION_TIME_ZONE,
    Dataset,
    install_current_views,
    timestamp,
)
from epl_forecast.storage import file_hash, json_bytes, write_immutable

SNAPSHOT_SCHEMA_VERSION = 1


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _qualified(connection, schema: str, table: str) -> str:
    database = connection.execute("SELECT current_database()").fetchone()[0]
    return f"{_ident(database)}.{_ident(schema)}.{_ident(table)}"


def snapshot_manifest_path(database: Path) -> Path:
    return database.with_suffix(database.suffix + ".manifest.json")


def _table_digest(connection, table: str) -> dict:
    relation = _qualified(connection, "canonical", f"{table}_observations")
    result = connection.execute(f"SELECT * FROM {relation} ORDER BY ALL")
    columns = [(column[0], str(column[1])) for column in result.description]
    digest = hashlib.sha256(json_bytes(columns))
    count = 0
    while rows := result.fetchmany(10_000):
        for row in rows:
            digest.update(json.dumps(row, default=str, separators=(",", ":")).encode())
            digest.update(b"\n")
        count += len(rows)
    return {"rows": count, "sha256": digest.hexdigest()}


def create_snapshot(
    source: Dataset,
    destination: Path,
    *,
    source_revision: str,
    manifest_path: Path | None = None,
) -> dict:
    """Materialize one closed canonical database and write its verification manifest."""
    destination = Path(destination)
    manifest_path = Path(manifest_path or snapshot_manifest_path(destination))
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.{uuid4().hex}.tmp"
    alias = f"snapshot_{uuid4().hex}"
    try:
        source.con.execute(f"ATTACH {_literal(str(temporary))} AS {alias}")
        try:
            source.con.execute(f"CREATE SCHEMA {alias}.canonical")
            source.con.execute(f"CREATE SCHEMA {alias}.metadata")
            for table in SCHEMAS:
                source.con.execute(
                    f"CREATE TABLE {alias}.canonical.{table}_observations AS "
                    f"SELECT * FROM {table}_observations"
                )
            source.con.execute(f"CHECKPOINT {alias}")
        finally:
            source.con.execute(f"DETACH {alias}")

        created_at = datetime.now(UTC).isoformat()
        with duckdb.connect(str(temporary)) as connection:
            connection.execute(SESSION_TIME_ZONE)
            tables = {table: _table_digest(connection, table) for table in SCHEMAS}
            data_revision = hashlib.sha256(json_bytes(tables)).hexdigest()
            internal = {
                "schema_version": SNAPSHOT_SCHEMA_VERSION,
                "created_at": created_at,
                "source_revision": source_revision,
                "data_revision": data_revision,
                "manifests": source.manifests,
                "tables": tables,
            }
            connection.execute(
                f"CREATE TABLE {_qualified(connection, 'metadata', 'snapshot')} AS "
                "SELECT ?::INTEGER AS schema_version, "
                "?::VARCHAR AS created_at, ?::VARCHAR AS source_revision, "
                "?::VARCHAR AS data_revision, ?::JSON AS manifest",
                [
                    SNAPSHOT_SCHEMA_VERSION,
                    created_at,
                    source_revision,
                    data_revision,
                    json.dumps(internal, separators=(",", ":")),
                ],
            )
            connection.execute("CHECKPOINT")
        temporary.replace(destination)
        manifest = {
            **internal,
            "database_bytes": destination.stat().st_size,
            "database_sha256": file_hash(destination),
        }
        try:
            manifest["source_http"] = source.http_metrics()
        except duckdb.Error:
            manifest["source_http"] = None
        manifest["source_client"] = source.store.metrics() if source.store else None
        write_immutable(manifest_path, json_bytes(manifest))
        return manifest
    finally:
        temporary.unlink(missing_ok=True)


def verify_snapshot(
    database: Path, manifest_path: Path | None = None, *, deep: bool = True
) -> dict:
    """Verify the closed database bytes, metadata, and logical table content."""
    database = Path(database)
    manifest_path = Path(manifest_path or snapshot_manifest_path(database))
    manifest = json.loads(manifest_path.read_text())
    if manifest["schema_version"] != SNAPSHOT_SCHEMA_VERSION:
        raise ValueError("Unsupported snapshot schema version")
    if database.stat().st_size != manifest["database_bytes"]:
        raise ValueError("Snapshot byte count does not match its manifest")
    if file_hash(database) != manifest["database_sha256"]:
        raise ValueError("Snapshot hash does not match its manifest")
    with duckdb.connect(str(database), read_only=True) as connection:
        connection.execute(SESSION_TIME_ZONE)
        row = connection.execute(
            "SELECT schema_version, source_revision, data_revision FROM "
            + _qualified(connection, "metadata", "snapshot")
        ).fetchone()
        if row != (
            manifest["schema_version"],
            manifest["source_revision"],
            manifest["data_revision"],
        ):
            raise ValueError("Snapshot metadata does not match its manifest")
        if deep:
            tables = {table: _table_digest(connection, table) for table in SCHEMAS}
            if tables != manifest["tables"]:
                raise ValueError("Snapshot table content does not match its manifest")
            if hashlib.sha256(json_bytes(tables)).hexdigest() != manifest["data_revision"]:
                raise ValueError("Snapshot data revision is invalid")
    return manifest


def restore_snapshot(
    source: Path,
    destination: Path,
    *,
    manifest_path: Path | None = None,
) -> dict:
    """Verify a snapshot and replace the local copy only after a complete transfer."""
    source = Path(source)
    destination = Path(destination)
    manifest_path = Path(manifest_path or snapshot_manifest_path(source))
    manifest = verify_snapshot(source, manifest_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.{uuid4().hex}.tmp"
    try:
        shutil.copyfile(source, temporary)
        if temporary.stat().st_size != manifest["database_bytes"]:
            raise ValueError("Restored snapshot byte count does not match its manifest")
        if file_hash(temporary) != manifest["database_sha256"]:
            raise ValueError("Restored snapshot hash does not match its manifest")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return manifest


class SnapshotDataset(Dataset):
    """Read canonical evidence from one verified immutable database revision."""

    def __init__(self, database: Path, cutoff=None, *, manifest_path: Path | None = None):
        self.snapshot_path = Path(database)
        self.snapshot_manifest = Path(manifest_path or snapshot_manifest_path(self.snapshot_path))
        manifest = verify_snapshot(self.snapshot_path, self.snapshot_manifest, deep=False)
        self.source_revision = manifest["source_revision"]
        self.data_revision = manifest["data_revision"]
        self.store = None
        self.workspace = None
        self.local_batches = set()
        self.cutoff = timestamp(cutoff) if cutoff is not None else None
        self.manifests = [
            item
            for item in manifest["manifests"]
            if self.cutoff is None
            or item.get("covers_history")
            or timestamp(item["request"]["retrieved_at"]) <= self.cutoff
        ]
        self.con = duckdb.connect()
        self.con.execute(SESSION_TIME_ZONE)
        self.con.execute(f"ATTACH {_literal(str(self.snapshot_path))} AS snapshot (READ_ONLY)")
        for table in SCHEMAS:
            where = (
                ""
                if self.cutoff is None
                else f" WHERE retrieved_at <= TIMESTAMPTZ '{self.cutoff.isoformat()}'"
            )
            self.con.execute(
                f"CREATE VIEW {table}_observations AS "
                f"SELECT * FROM snapshot.canonical.{table}_observations{where}"
            )
        install_current_views(self.con)

    def verify(self):
        return verify_snapshot(self.snapshot_path, self.snapshot_manifest)
