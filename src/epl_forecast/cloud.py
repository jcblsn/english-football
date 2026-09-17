"""Move durable pipeline files between an ephemeral workspace and R2."""

import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from epl_forecast.datasets import KEYS, SCHEMAS, Dataset
from epl_forecast.storage import R2Store, file_hash, json_bytes, sha256_bytes


def collection_state(records: list[dict]) -> dict:
    latest = {}
    for record in sorted(records, key=lambda row: row["retrieved_at"]):
        latest[record["url"]] = record
    return {"schema_version": 1, "latest_by_url": latest}


def manifest_state(manifests: list[dict]) -> dict:
    unique = {manifest["batch_id"]: manifest for manifest in manifests}
    return {
        "schema_version": 1,
        "manifests": [unique[key] for key in sorted(unique)],
    }


def _upload_missing(
    store: R2Store, root: Path, paths: list[Path], existing: set[str] | None = None
) -> int:
    pending = [
        path
        for path in paths
        if not (
            path.relative_to(root).as_posix() in existing
            if existing is not None
            else store.exists(path.relative_to(root).as_posix())
        )
    ]

    def upload(path: Path) -> None:
        store.upload(path, path.relative_to(root).as_posix(), immutable=True)

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(upload, pending))
    return len(pending)


def _same_audit(remote: dict | None, path: Path) -> bool:
    def content(report: dict) -> dict:
        return {k: v for k, v in report.items() if k not in {"completed_at", "audited_at"}}

    return remote is not None and content(remote) == content(json.loads(path.read_text()))


def sync_data(
    root: Path,
    store: R2Store,
    *,
    manifest_paths: list[Path],
    request_paths: list[Path],
) -> dict:
    """Upload objects from this collection, then advance their state pointers."""
    root = Path(root)
    manifest_paths = sorted(Path(path) for path in manifest_paths)
    request_paths = sorted(Path(path) for path in request_paths)
    new_manifests = [json.loads(path.read_text()) for path in manifest_paths]
    new_requests = [json.loads(path.read_text()) for path in request_paths]
    paths = [*manifest_paths, *request_paths]
    paths.extend(root / record["raw_path"] for record in new_requests)
    paths.extend(root / item["path"] for manifest in new_manifests for item in manifest["files"])
    paths.extend((root / "audits" / "api_football").glob("*.json"))
    uploaded = _upload_missing(store, root, sorted(set(paths)))
    changed = bool(new_manifests or new_requests)
    audits = [
        path
        for path in sorted((root / "audits").glob("*.json"))
        if path.is_file()
        and (changed or not _same_audit(store.get_json(path.relative_to(root).as_posix()), path))
    ]
    for path in audits:
        store.upload(path, path.relative_to(root).as_posix())
    remote_manifests = store.get_json("state/manifests.json", {}).get("manifests", [])
    remote_requests = list(
        store.get_json("state/collection.json", {}).get("latest_by_url", {}).values()
    )
    manifests = manifest_state([*remote_manifests, *new_manifests])
    requests = collection_state([*remote_requests, *new_requests])
    if changed:
        store.put_json("state/manifests.json", manifests)
        store.put_json("state/collection.json", requests)
    return {
        "uploaded": uploaded,
        "audits": len(audits),
        "manifests": len(manifests["manifests"]),
        "request_urls": len(requests["latest_by_url"]),
    }


def compaction_due(store: R2Store, max_incremental_batches: int = 250) -> bool:
    manifests = store.get_json("state/manifests.json", {}).get("manifests", [])
    incremental = sum(not manifest.get("covers_history") for manifest in manifests)
    return incremental >= max_incremental_batches


def sync_tree(root: Path, store: R2Store, prefix: str) -> dict:
    root = Path(root)
    existing = set(store.keys(prefix.rstrip("/") + "/"))
    paths = sorted(path for path in root.rglob("*") if path.is_file())
    pending = [
        path
        for path in paths
        if f"{prefix.rstrip('/')}/{path.relative_to(root).as_posix()}" not in existing
    ]

    def upload(path: Path) -> None:
        key = f"{prefix.rstrip('/')}/{path.relative_to(root).as_posix()}"
        store.upload(path, key, immutable=True)

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(upload, pending))
    return {"uploaded": len(pending), "files": len(paths), "prefix": prefix}


def compact_canonical(store: R2Store) -> dict:
    """Compact the R2 canonical catalog into one batch and switch the catalog to it."""
    source = list(
        {
            manifest["batch_id"]: manifest
            for manifest in store.get_json("state/manifests.json", {}).get("manifests", [])
        }.values()
    )
    batch_id = sha256_bytes(
        json_bytes(
            {
                "format": "canonical-compaction-v1",
                "source_batches": sorted(manifest["batch_id"] for manifest in source),
            }
        )
    )
    with tempfile.TemporaryDirectory(prefix="page324-compact-") as temporary:
        staging = Path(temporary)
        data = Dataset(store=store, manifests=source)
        files = []
        rows = {}
        try:
            for table in SCHEMAS:
                records = f"SELECT DISTINCT * FROM {table}_observations"
                count = data.rows(f"SELECT count(*) AS n FROM ({records})")[0]["n"]
                rows[table] = count
                if not count:
                    continue
                path = staging / "parquet" / "compacted" / batch_id / f"{table}.parquet"
                path.parent.mkdir(parents=True, exist_ok=True)
                keys = ",".join([*KEYS[table], "provider", "retrieved_at", "source_sha256"])
                data.con.execute(
                    f"COPY (SELECT * FROM ({records}) ORDER BY {keys}) "
                    "TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
                    [str(path)],
                )
                files.append(
                    {
                        "table": table,
                        "path": path.relative_to(staging).as_posix(),
                        "sha256": file_hash(path),
                    }
                )
        finally:
            data.close()
        manifest = {
            "batch_id": batch_id,
            "covers_history": True,
            "request": {
                "provider": "canonical_compaction",
                "retrieved_at": max(manifest["request"]["retrieved_at"] for manifest in source),
                "evidence_basis": "retained",
                "source_sha256": sha256_bytes(
                    json_bytes(sorted(manifest["batch_id"] for manifest in source))
                ),
                "context": {"kind": "canonical_compaction"},
            },
            "files": files,
            "rows": rows,
        }
        for file in files:
            store.upload(staging / file["path"], file["path"], immutable=True)
        store.put_json(f"manifests/{batch_id}.json", manifest, immutable=True)
        store.put_json("state/manifests.json", manifest_state([manifest]))
    return {"batch_id": batch_id, "files": len(files), "rows": rows}
