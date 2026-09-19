"""Move issued prospective forecasts into the cumulative typed result stores."""

import argparse
import json
from pathlib import Path

import duckdb

from epl_forecast.competitions import COMPETITION_IDS
from epl_forecast.pipeline import commit_result_store, prepare_result_store
from epl_forecast.results import store_public_projection, write_forecast_result
from epl_forecast.storage import (
    R2Store,
    file_hash,
    json_bytes,
    load_environment,
    sha256_bytes,
    write_json,
)


def _issued_archive(publish_store, competition_id: str) -> tuple[dict, str]:
    key = f"forecasts/{competition_id}/archive.json"
    payload = publish_store.get_bytes(key)
    archive = json.loads(payload)
    if archive.get("schema_version") != 1 or archive.get("competition_id") != competition_id:
        raise ValueError(f"Invalid issued archive: {key}")
    return archive, sha256_bytes(payload)


def _source_revision(run: dict) -> str:
    source = run.get("data_manifest") or run.get("live_snapshot") or run
    return sha256_bytes(json_bytes(source))


def _validate_release(publish_store, pointer: dict, public_payload: bytes) -> None:
    receipt_key = pointer.get("release_href")
    if receipt_key is None:
        return
    receipt = publish_store.get_json(receipt_key)
    if receipt is None:
        raise ValueError(f"Missing release receipt: {receipt_key}")
    if receipt.get("forecast_id") != pointer["forecast_id"]:
        raise ValueError(f"Release receipt identity differs: {receipt_key}")
    if receipt.get("document_sha256") != sha256_bytes(public_payload):
        raise ValueError(f"Release receipt digest differs: {receipt_key}")


def _database_ids(database: Path, table: str) -> list[str]:
    with duckdb.connect(str(database), read_only=True) as connection:
        return [
            row[0]
            for row in connection.execute(
                f"SELECT result_id FROM forecast_result.{table} ORDER BY result_id"
            ).fetchall()
        ]


def stage(data_store, publish_store, root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    stores = []
    for competition_id in COMPETITION_IDS:
        database = root / f"{competition_id}.duckdb"
        previous_version = prepare_result_store(data_store, competition_id, database)
        archive, archive_sha256 = _issued_archive(publish_store, competition_id)
        forecast_ids = sorted(row["forecast_id"] for row in archive["forecasts"])
        for index, pointer in enumerate(
            sorted(archive["forecasts"], key=lambda row: row["forecast_id"]), start=1
        ):
            forecast_id = pointer["forecast_id"]
            if pointer.get("competition_id") != competition_id:
                raise ValueError(f"Issued forecast competition differs: {forecast_id}")
            public_payload = publish_store.get_bytes(pointer["href"])
            public = json.loads(public_payload)
            _validate_release(publish_store, pointer, public_payload)
            prefix = f"runs/forecasts/{forecast_id}/{competition_id}"
            forecast = data_store.get_json(f"{prefix}/forecast.json")
            run = data_store.get_json(f"{prefix}/run.json")
            if forecast is None or run is None:
                raise ValueError(f"Issued forecast has no complete private source: {prefix}")
            if (
                forecast.get("competition_id") != competition_id
                or forecast.get("season_id") != public.get("season_id")
                or public.get("forecast_id") != forecast_id
            ):
                raise ValueError(f"Issued forecast identity differs: {forecast_id}")
            public_matches = {row["match_id"] for row in public.get("matches", [])}
            private_matches = {row["match_id"] for row in forecast.get("matches", [])}
            if not public_matches <= private_matches:
                raise ValueError(
                    f"Issued matches are absent from the private source: {forecast_id}"
                )
            result = write_forecast_result(
                database,
                forecast,
                run,
                input_revision=_source_revision(run),
                result_id=forecast_id,
            )
            store_public_projection(database, forecast_id, public)
            print(
                json.dumps(
                    {
                        "competition_id": competition_id,
                        "forecast": index,
                        "forecasts": len(forecast_ids),
                        "result_id": forecast_id,
                        "status": result["status"],
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        result_ids = _database_ids(database, "forecast_runs")
        public_ids = _database_ids(database, "forecast_public_documents")
        missing_results = sorted(set(forecast_ids) - set(result_ids))
        missing_public = sorted(set(forecast_ids) - set(public_ids))
        if missing_results or missing_public:
            raise ValueError(
                f"Incomplete typed migration for {competition_id}: "
                f"results={missing_results}, public={missing_public}"
            )
        stores.append(
            {
                "competition_id": competition_id,
                "archive_sha256": archive_sha256,
                "forecast_ids": forecast_ids,
                "database": database.name,
                "database_bytes": database.stat().st_size,
                "database_sha256": file_hash(database),
                "previous_pointer_version": previous_version,
            }
        )
    manifest = {"schema_version": 1, "mode": "staged", "stores": stores}
    write_json(root / "migration.json", manifest)
    return manifest


def apply(data_store, publish_store, root: Path) -> dict:
    manifest = json.loads((root / "migration.json").read_text())
    applied = []
    for row in manifest["stores"]:
        competition_id = row["competition_id"]
        _, archive_sha256 = _issued_archive(publish_store, competition_id)
        if archive_sha256 != row["archive_sha256"]:
            raise ValueError(f"Issued archive changed after staging: {competition_id}")
        database = root / row["database"]
        if database.stat().st_size != row["database_bytes"]:
            raise ValueError(f"Staged result size differs: {competition_id}")
        if file_hash(database) != row["database_sha256"]:
            raise ValueError(f"Staged result digest differs: {competition_id}")
        result_ids = _database_ids(database, "forecast_runs")
        public_ids = _database_ids(database, "forecast_public_documents")
        if not set(row["forecast_ids"]) <= set(result_ids) or not set(row["forecast_ids"]) <= set(
            public_ids
        ):
            raise ValueError(f"Staged result is incomplete: {competition_id}")
        pointer_key = f"state/results/{competition_id}.json"
        pointer, version = data_store.get_json_versioned(pointer_key)
        if pointer is not None and pointer.get("database_sha256") == row["database_sha256"]:
            applied.append({"competition_id": competition_id, "status": "unchanged"})
            continue
        if version != row["previous_pointer_version"]:
            raise ValueError(f"Result pointer changed after staging: {competition_id}")
        committed = commit_result_store(data_store, competition_id, database, version)
        applied.append(
            {
                "competition_id": competition_id,
                "status": "committed",
                "database_key": committed["database_key"],
            }
        )
    return {"schema_version": 1, "applied": applied}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("stage", "apply"))
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    load_environment()
    data_store = R2Store.from_environment("R2_DATA_BUCKET")
    publish_store = R2Store.from_environment("R2_PUBLISH_BUCKET")
    result = (
        stage(data_store, publish_store, args.root)
        if args.mode == "stage"
        else apply(data_store, publish_store, args.root)
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
