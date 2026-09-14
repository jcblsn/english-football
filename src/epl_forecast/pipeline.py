"""Run collection, verified forecasts and publication from an ephemeral workspace."""

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from epl_forecast.cloud import compact_canonical, sync_data, sync_tree
from epl_forecast.competitions import COMPETITION_IDS
from epl_forecast.data.capture import SourceAccessError, writer_lock
from epl_forecast.data.collect import collect
from epl_forecast.datasets import Dataset
from epl_forecast.ledger import build_ledger, build_record, realized_outcomes
from epl_forecast.publication import (
    carry_forward_impacts,
    derive_forecast,
    load_policy,
    materialize_publication,
    publish_document,
    publish_documents_to_store,
    rebuild_index,
)
from epl_forecast.storage import (
    file_hash,
    json_bytes,
    r2_store_if_configured,
    sha256_bytes,
    write_immutable,
    write_json,
)

PRODUCT_MODEL = "M7-xg-v1"
PRODUCT_CONFIG = Path("configs/product.toml")
LEAGUES = COMPETITION_IDS
REPOSITORY = Path(__file__).resolve().parents[2]


def snapshot_id(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H%M%SZ")


def _run(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, text=True, capture_output=True, check=False, cwd=REPOSITORY)


def run_forecast(data: Path, league: str, cutoff: datetime, output: Path, simulations: int):
    return _run(
        [
            sys.executable,
            "-m",
            "epl_forecast.cli",
            "forecast",
            "--data",
            str(data),
            "--competition",
            league,
            "--cutoff",
            cutoff.isoformat(),
            "--config",
            str(PRODUCT_CONFIG),
            "--model",
            PRODUCT_MODEL,
            "--output",
            str(output),
            "--simulations",
            str(simulations),
        ]
    )


def verify_archive(data: Path, archive: Path, output: Path):
    return _run(
        [
            sys.executable,
            "-m",
            "epl_forecast.cli",
            "verify",
            "--archive",
            str(archive),
            "--data",
            str(data),
            "--output",
            str(output),
        ]
    )


def information_fingerprint(data):
    """A digest of the inputs that can change a forecast; a new digest makes a run due."""
    fields = {
        "fixtures": "match_id, kickoff_time, status, home_goals, away_goals",
        "memberships": "player_id, team_id, season_id, basis",
        "availability": "player_id, fpl_code, scope, status, reason, chance_next_round",
        "team_process": "match_id, team_id, xg",
        "odds": "match_id, family, home_odds, draw_odds, away_odds",
    }
    records = {
        table: data.rows(f"SELECT DISTINCT {columns} FROM {table} ORDER BY ALL")
        for table, columns in fields.items()
    }
    return sha256_bytes(json.dumps(records, default=str, sort_keys=True).encode())


def install_launch_agent(label, arguments, root, interval_seconds, logs=None):
    """Install and start a per-user launchd job, replacing any earlier one."""
    import os
    import plistlib

    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    logs = logs or label.rsplit(".", 1)[-1]
    path = Path.home() / "Library/LaunchAgents" / f"{label}.plist"
    config = {
        "Label": label,
        "ProgramArguments": list(arguments),
        "WorkingDirectory": str(REPOSITORY),
        "StartInterval": int(interval_seconds),
        "RunAtLoad": True,
        "ProcessType": "Background",
        "StandardOutPath": str(root / f"{logs}.log"),
        "StandardErrorPath": str(root / f"{logs}-errors.log"),
        "EnvironmentVariables": {"OPENBLAS_NUM_THREADS": "1"},
    }
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", f"{domain}/{label}"], capture_output=True, check=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plistlib.dumps(config))
    subprocess.run(["launchctl", "bootstrap", domain, str(path)], check=True)
    return path


FORECAST_CODE = (
    Path("src/epl_forecast/models"),
    Path("src/epl_forecast/artifacts.py"),
    Path("src/epl_forecast/cli.py"),
    Path("src/epl_forecast/competitions.py"),
    Path("src/epl_forecast/data/efl_adjustments.json"),
    Path("src/epl_forecast/data/pl_adjustments.json"),
    Path("src/epl_forecast/data/rules.py"),
    Path("src/epl_forecast/data/teams.csv"),
    Path("src/epl_forecast/datasets.py"),
    Path("src/epl_forecast/live.py"),
    Path("src/epl_forecast/live_forecast.py"),
    Path("src/epl_forecast/market.py"),
    Path("src/epl_forecast/pipeline.py"),
    Path("src/epl_forecast/postseason.py"),
    Path("src/epl_forecast/publication.py"),
    Path("src/epl_forecast/sanctions.py"),
    Path("src/epl_forecast/schema.py"),
    Path("src/epl_forecast/simulation.py"),
    Path("src/epl_forecast/training.py"),
    Path("src/epl_forecast/verification.py"),
    Path("configs/product.toml"),
    Path("configs/market_pool.json"),
    Path("configs/publication.toml"),
)


def production_fingerprint(data_fingerprint: str) -> str:
    paths = []
    for path in FORECAST_CODE:
        paths.extend(sorted(path.rglob("*.py")) if path.is_dir() else [path])
    code = {str(path): file_hash(path) for path in paths}
    return sha256_bytes(json_bytes({"data": data_fingerprint, "forecast_code": code}))


def due(state: dict, fingerprint: str, competition: str) -> bool:
    return state.get("competitions", {}).get(competition, {}).get("fingerprint") != fingerprint


def operate(
    data: Path = Path("data"),
    site: Path = Path("site"),
    runs: Path = Path("runs/product"),
    simulations: int = 10000,
    interval_hours: float | None = None,
    force: bool = False,
    collect_first: bool = True,
    data_store=None,
    publish_store=None,
) -> dict:
    data, site, runs = Path(data), Path(site), Path(runs)
    data_store = data_store if data_store is not None else r2_store_if_configured("R2_DATA_BUCKET")
    publish_store = (
        publish_store if publish_store is not None else r2_store_if_configured("R2_PUBLISH_BUCKET")
    )
    if (data_store is None) != (publish_store is None):
        raise ValueError("Configure both R2 buckets or neither bucket")
    policy = load_policy()
    result = {"status": "ok", "published": [], "collection": None}
    if collect_first:
        try:
            with writer_lock(data):
                result["collection"] = collect(data, store=data_store)
                if data_store:
                    result["data_sync"] = sync_data(data, data_store)
                    if result["data_sync"]["uploaded"]:
                        result["compaction"] = compact_canonical(data, data_store)
        except SourceAccessError as error:
            return {"status": "skipped", "reason": str(error)}
    now = datetime.now(UTC)
    dataset = Dataset(data, now, store=data_store)
    try:
        fingerprint = production_fingerprint(information_fingerprint(dataset))
        outcomes = realized_outcomes(dataset.fixtures())
    finally:
        dataset.close()
    state_path = runs / "state.json"
    state = (
        data_store.get_json("state/forecast.json", {})
        if data_store
        else json.loads(state_path.read_text())
        if state_path.exists()
        else {}
    )
    pending = [league for league in LEAGUES if force or due(state, fingerprint, league)]
    if not pending:
        result.update(status="unchanged", reason="No new information since the last publication")
        if publish_store:
            materialize_publication(publish_store, site)
            record = build_record(site, outcomes, policy)
            publish_store.put_json("record.json", record)
        else:
            build_ledger(site, outcomes, policy)
        return result
    if publish_store:
        materialize_publication(publish_store, site)
    snapshot = snapshot_id(now)
    attempt = runs / snapshot
    documents, failures = [], []
    for league in pending:
        archive = attempt / league
        forecast = run_forecast(data, league, now, archive, simulations)
        write_immutable(
            attempt / f"{league}-forecast.log", (forecast.stdout + forecast.stderr).encode()
        )
        if forecast.returncode:
            failures.append(
                {"league": league, "stage": "forecast", "detail": forecast.stderr[-800:]}
            )
            continue
        reports = attempt / f"{league}-verification"
        verification = verify_archive(data, archive, reports)
        write_immutable(
            attempt / f"{league}-verify.log", (verification.stdout + verification.stderr).encode()
        )
        if verification.returncode:
            failures.append(
                {"league": league, "stage": "verify", "detail": verification.stdout[-800:]}
            )
            continue
        report = json.loads((reports / "verification.json").read_text())
        documents.append(
            carry_forward_impacts(
                site,
                derive_forecast(
                    json.loads((archive / "forecast.json").read_text()),
                    json.loads((archive / "run.json").read_text()),
                    snapshot,
                    report["archives"][str(archive)],
                    public_model_version=policy["product"]["model_version"],
                ),
            )
        )
    # A division that fails holds back only itself. The snapshot carries the divisions that pass.
    if not documents:
        result.update(status="failed", failures=failures, attempt=str(attempt))
        write_immutable(attempt / "pipeline.json", json_bytes(result))
        if data_store:
            sync_tree(attempt, data_store, f"runs/forecasts/{snapshot}")
        return result
    if publish_store:
        result["private_sync"] = sync_tree(attempt, data_store, f"runs/forecasts/{snapshot}")
        index = publish_documents_to_store(publish_store, documents, policy)
        materialize_publication(publish_store, site)
        record = build_record(site, outcomes, policy)
        publish_store.put_json("record.json", record)
    else:
        for document in documents:
            publish_document(site, document, policy)
        index = rebuild_index(site, policy)
        record = build_ledger(site, outcomes, policy)
    for document in documents:
        result["published"].append(f"{snapshot}/{document['competition_id']}")
    result.update(
        status="partial" if failures else "ok",
        failures=failures,
        attempt=str(attempt),
        snapshot_id=snapshot,
        snapshots=len(index["snapshots"]),
        scored_matches=record["summary"].get("overall", {}).get("scored", 0),
    )
    write_immutable(attempt / "pipeline.json", json_bytes(result))
    competition_state = state.setdefault("competitions", {})
    for document in documents:
        competition_state[document["competition_id"]] = {
            "fingerprint": fingerprint,
            "published_at": now.isoformat(),
            "snapshot_id": snapshot,
        }
    if data_store:
        data_store.put_json("state/forecast.json", state)
        sync_tree(attempt, data_store, f"runs/forecasts/{snapshot}")
    else:
        write_json(state_path, state)
    return result
