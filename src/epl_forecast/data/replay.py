"""Replay every retained raw capture in R2 with the current normalizers."""

import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

from epl_forecast.cloud import canonical_rows, publish_base_batch
from epl_forecast.data import api_football as api
from epl_forecast.data import football_data, fpl, kalshi, understat_ingest
from epl_forecast.data.capture import decode_capture
from epl_forecast.datasets import Dataset
from epl_forecast.storage import R2Store, json_bytes, sha256_bytes

INGESTORS = {"football_data": football_data, "understat": understat_ingest, "fpl": fpl}


def replay_order(record: dict) -> tuple:
    """Captures that later ingestion reads come first: identities, then histories, then links."""
    provider, context = record["provider"], record["context"]
    phase = 0
    if provider == "api_football" and context.get("endpoint") in (
        "injuries",
        "sidelined",
        "transfers",
    ):
        phase = 1
    elif provider == "football_data" and context.get("kind") == "latest_odds":
        phase = 2
    elif provider == "understat":
        phase = 2 if context.get("kind") == "league" else 3
    elif provider == "fpl":
        phase = 4
    elif provider == "kalshi":
        phase = 5
    return phase, record["retrieved_at"], record["url"], record["source_sha256"]


@contextmanager
def without_r2_environment():
    """Hide the R2 settings, so that each ingestion reader sees only the replay workspace."""
    saved = {name: os.environ.pop(name) for name in list(os.environ) if name.startswith("R2_")}
    try:
        yield
    finally:
        os.environ.update(saved)


def normalize_capture(workspace: Path, record: dict, payload: bytes, understat_context, kalshi_run):
    """Normalize one raw capture into the workspace. Returns the shared Understat context."""
    provider = record["provider"]
    if provider == "efl_rules":
        return understat_context
    if provider == "api_football":
        if record["context"].get("endpoint") != "status":
            api.normalize(record, json.loads(payload), workspace)
    elif provider == "kalshi":
        # The run publishes the series completion snapshot that production
        # wrote, so a replayed history is not missing the Kalshi scopes.
        kalshi.ingest(workspace, record, payload, run=kalshi_run)
    elif provider == "understat" and record["context"].get("kind") == "players":
        if understat_context is None:
            understat_context = understat_ingest.IngestContext(workspace)
        understat_ingest.ingest(workspace, record, payload, understat_context)
    else:
        INGESTORS[provider].ingest(workspace, record, payload)
    return understat_context


def replay_canonical(store: R2Store, *, publish: bool = False, workers: int = 16) -> dict:
    """Rebuild the canonical history from the R2 raw captures in a temporary workspace.

    Without `publish`, the result is a report only. With `publish`, the replayed history becomes
    one base batch that replaces the catalog batches read at the start.
    """
    catalog = store.get_json("state/manifests.json", {}).get("manifests", [])
    replaced = {manifest["batch_id"] for manifest in catalog}
    current = Dataset(store=store, manifests=catalog)
    try:
        current_rows = canonical_rows(current)
    finally:
        current.close()
    keys = sorted(key for key in store.keys("requests/") if key.endswith(".json"))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        records = sorted(pool.map(store.get_json, keys), key=replay_order)
    with tempfile.TemporaryDirectory(prefix="page324-replay-") as temporary:
        workspace = Path(temporary)

        def download(record):
            path = workspace / record["raw_path"]
            store.download(record["raw_path"], path)
            try:
                decode_capture(record, path.read_bytes())
            except ValueError:
                raise ValueError(f"Raw capture hash mismatch: {record['raw_path']}") from None

        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(download, {record["raw_path"]: record for record in records}.values()))
        with without_r2_environment():
            understat_context = None
            kalshi_run = kalshi.SeriesRun()
            for record in records:
                payload = decode_capture(record, (workspace / record["raw_path"]).read_bytes())
                understat_context = normalize_capture(
                    workspace, record, payload, understat_context, kalshi_run
                )
            data = Dataset(workspace=workspace)
        try:
            data.verify()
            data.fixtures()
            rows = canonical_rows(data)
            result = {
                "status": "checked",
                "requests_replayed": len(records),
                "replaced_batches": len(replaced),
                "rows": rows,
                "current_rows": current_rows,
            }
            if publish:
                request = {
                    "provider": "canonical_replay",
                    "retrieved_at": max(record["retrieved_at"] for record in records),
                    "evidence_basis": "retained",
                    "source_sha256": sha256_bytes(
                        json_bytes(sorted(record["source_sha256"] for record in records))
                    ),
                    "context": {"kind": "canonical_replay", "requests": len(records)},
                }
                manifest = publish_base_batch(store, data, request, replaced, "replayed")
                result.update(status="published", batch_id=manifest["batch_id"])
        finally:
            data.close()
    return result
