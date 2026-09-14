"""Move durable pipeline files between an ephemeral workspace and R2."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from epl_forecast.storage import R2Store

IMMUTABLE_DATA_DIRECTORIES = ("raw", "requests", "parquet", "manifests")


def read_manifests(root: Path) -> list[dict]:
    return [
        json.loads(path.read_text()) for path in sorted((Path(root) / "manifests").glob("*.json"))
    ]


def read_requests(root: Path) -> list[dict]:
    return [
        json.loads(path.read_text()) for path in sorted((Path(root) / "requests").glob("*.json"))
    ]


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


def _upload_missing(store: R2Store, root: Path, paths: list[Path], existing: set[str]) -> int:
    pending = [path for path in paths if path.relative_to(root).as_posix() not in existing]

    def upload(path: Path) -> None:
        store.upload(path, path.relative_to(root).as_posix(), immutable=True)

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(upload, pending))
    return len(pending)


def sync_data(root: Path, store: R2Store) -> dict:
    root = Path(root)
    existing = set(store.keys())
    uploaded = 0
    for directory in IMMUTABLE_DATA_DIRECTORIES:
        paths = sorted(path for path in (root / directory).rglob("*") if path.is_file())
        uploaded += _upload_missing(store, root, paths, existing)
        existing.update(path.relative_to(root).as_posix() for path in paths)
    audits = sorted(path for path in (root / "audits").glob("*.json") if path.is_file())
    for path in audits:
        store.upload(path, path.relative_to(root).as_posix())
    remote_manifests = store.get_json("state/manifests.json", {}).get("manifests", [])
    remote_requests = list(
        store.get_json("state/collection.json", {}).get("latest_by_url", {}).values()
    )
    manifests = manifest_state([*remote_manifests, *read_manifests(root)])
    requests = collection_state([*remote_requests, *read_requests(root)])
    store.put_json("state/manifests.json", manifests)
    store.put_json("state/collection.json", requests)
    return {
        "uploaded": uploaded,
        "audits": len(audits),
        "manifests": len(manifests["manifests"]),
        "request_urls": len(requests["latest_by_url"]),
    }


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
