"""Run collection, verified forecasts and publication from an ephemeral workspace."""

import json
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from epl_forecast.cloud import sync_data, sync_tree
from epl_forecast.competitions import COMPETITION_IDS
from epl_forecast.data.capture import SourceAccessError, writer_lock
from epl_forecast.data.collect import collect
from epl_forecast.datasets import Dataset
from epl_forecast.personnel import current_adjustments
from epl_forecast.publication import (
    derive_forecast,
    load_policy,
    publish_documents,
    update_impact_state,
)
from epl_forecast.record import realized_outcomes, update_record
from epl_forecast.schema import Fixture
from epl_forecast.storage import (
    file_hash,
    json_bytes,
    r2_store_if_configured,
    sha256_bytes,
    write_immutable,
)

PRODUCT_MODEL = "M7-xg-v1"
PRODUCT_CONFIG = Path("configs/product.toml")
LEAGUES = COMPETITION_IDS
REPOSITORY = Path(__file__).resolve().parents[2]


def forecast_id(moment: datetime) -> str:
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


def training_competitions(competition_id: str) -> list[str]:
    with PRODUCT_CONFIG.open("rb") as stream:
        config = tomllib.load(stream)
    model = next(spec for spec in config["models"] if spec["id"] == PRODUCT_MODEL)
    competitions = model.get("train_competitions", {})
    return list(competitions.get(competition_id, [competition_id]))


def information_fingerprint(data, competition_id: str):
    """Digest only the canonical values that one competition forecast consumes."""
    training = training_competitions(competition_id)
    placeholders = ", ".join("?" for _ in training)
    queries = {
        "fixtures": (
            "SELECT DISTINCT match_id, competition_id, season_id, stage, home_team_id, "
            "away_team_id, match_date, kickoff_time, status, home_goals, away_goals "
            f"FROM fixtures WHERE competition_id IN ({placeholders}) "
            "AND (competition_id=? OR status='finished') ORDER BY ALL",
            [*training, competition_id],
        ),
        "team_process": (
            "SELECT DISTINCT match_id, team_id, xg FROM team_process "
            f"WHERE competition_id IN ({placeholders}) ORDER BY ALL",
            training,
        ),
        "team_statistics": (
            "SELECT DISTINCT match_id, team_id, expected_goals FROM team_statistics "
            f"WHERE expected_goals IS NOT NULL AND competition_id IN ({placeholders}) ORDER BY ALL",
            training,
        ),
        "odds": (
            "SELECT DISTINCT match_id, family, home_odds, draw_odds, away_odds FROM odds "
            "WHERE competition_id=? AND season_id=(SELECT max(season_id) FROM fixtures "
            "WHERE competition_id=?) ORDER BY ALL",
            [competition_id, competition_id],
        ),
        "standings": (
            "SELECT DISTINCT team_id, points, played, wins, draws, losses, goals_for, "
            "goals_against, goal_difference FROM standings WHERE competition_id=? "
            "AND season_id=(SELECT max(season_id) FROM fixtures WHERE competition_id=?) "
            "ORDER BY ALL",
            [competition_id, competition_id],
        ),
        "teams": (
            "SELECT DISTINCT team_id, name FROM teams WHERE team_id IN ("
            "SELECT home_team_id FROM fixtures WHERE competition_id=? AND "
            "season_id=(SELECT max(season_id) FROM fixtures WHERE competition_id=?) UNION "
            "SELECT away_team_id FROM fixtures WHERE competition_id=? AND "
            "season_id=(SELECT max(season_id) FROM fixtures WHERE competition_id=?)) ORDER BY ALL",
            [competition_id] * 4,
        ),
    }
    records = {name: data.rows(sql, parameters) for name, (sql, parameters) in queries.items()}
    upcoming = [
        row
        for row in data.fixtures()
        if row["competition_id"] == competition_id
        and row["stage"] == "regular"
        and row["status"] != "finished"
        and row["kickoff_time"] is not None
        and row["match_date"] is not None
    ]
    records["personnel"] = current_adjustments(
        data,
        [
            Fixture(
                row["match_id"],
                competition_id,
                row["season_id"],
                row["match_date"],
                row["home_team_id"],
                row["away_team_id"],
            )
            for row in upcoming
        ],
        {row["match_id"]: row["kickoff_time"] for row in upcoming},
        data.cutoff or datetime.now(UTC),
    )
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


MODEL_CODE = (
    Path("src/epl_forecast/models"),
    Path("src/epl_forecast/competitions.py"),
    Path("src/epl_forecast/data/efl_adjustments.json"),
    Path("src/epl_forecast/data/pl_adjustments.json"),
    Path("src/epl_forecast/data/rules.py"),
    Path("src/epl_forecast/data/teams.csv"),
    Path("src/epl_forecast/datasets.py"),
    Path("src/epl_forecast/live.py"),
    Path("src/epl_forecast/personnel.py"),
    Path("src/epl_forecast/live_forecast.py"),
    Path("src/epl_forecast/market.py"),
    Path("src/epl_forecast/postseason.py"),
    Path("src/epl_forecast/sanctions.py"),
    Path("src/epl_forecast/schema.py"),
    Path("src/epl_forecast/simulation.py"),
    Path("src/epl_forecast/training.py"),
    Path("configs/product.toml"),
    Path("configs/market_pool.json"),
)


def model_code_hashes() -> dict[str, str]:
    paths = []
    for path in MODEL_CODE:
        paths.extend(sorted(path.rglob("*.py")) if path.is_dir() else [path])
    return {str(path): file_hash(path) for path in paths}


def production_fingerprint(data_fingerprint: str, model_version: str) -> str:
    """A public model version change makes every division due, so no forecast keeps the old label."""
    code = model_code_hashes()
    return sha256_bytes(
        json_bytes(
            {"data": data_fingerprint, "forecast_code": code, "model_version": model_version}
        )
    )


def collect_and_sync(data: Path, data_store) -> tuple[dict, dict]:
    """Collect into the workspace, then upload only the objects that this collection created."""
    with writer_lock(data):
        old_manifests = set((data / "manifests").glob("*.json"))
        old_requests = set((data / "requests").glob("*.json"))
        collection = collect(data, store=data_store)
        synced = sync_data(
            data,
            data_store,
            manifest_paths=list(set((data / "manifests").glob("*.json")) - old_manifests),
            request_paths=list(set((data / "requests").glob("*.json")) - old_requests),
        )
    return collection, synced


def due(state: dict, fingerprint: str, competition: str) -> bool:
    return state.get("competitions", {}).get(competition, {}).get("fingerprint") != fingerprint


def operate(
    data: Path = Path("data"),
    runs: Path = Path("runs/product"),
    simulations: int = 10000,
    force: bool = False,
    collect_first: bool = True,
    data_store=None,
    publish_store=None,
) -> dict:
    data, runs = Path(data), Path(runs)
    data_store = data_store if data_store is not None else r2_store_if_configured("R2_DATA_BUCKET")
    publish_store = (
        publish_store if publish_store is not None else r2_store_if_configured("R2_PUBLISH_BUCKET")
    )
    if data_store is None or publish_store is None:
        raise ValueError("Production needs both R2 buckets")
    policy = load_policy()
    result = {"status": "ok", "published": [], "collection": None}
    if collect_first:
        try:
            result["collection"], result["data_sync"] = collect_and_sync(data, data_store)
        except SourceAccessError as error:
            return {"status": "skipped", "reason": str(error)}
    now = datetime.now(UTC)
    model_version = policy["product"]["model_version"]
    dataset = Dataset(data, now, store=data_store)
    try:
        fingerprints = {
            competition_id: production_fingerprint(
                information_fingerprint(dataset, competition_id), model_version
            )
            for competition_id in LEAGUES
        }
        outcomes = realized_outcomes(dataset.fixtures())
    finally:
        dataset.close()
    state = data_store.get_json("state/forecast.json", {})
    pending = [league for league in LEAGUES if force or due(state, fingerprints[league], league)]
    if not pending:
        result.update(status="unchanged", reason="No new information since the last publication")
        previous = publish_store.get_json("record.json")
        record = update_record(previous, [], outcomes, policy)
        if previous is None or {**previous, "updated_at": None} != {**record, "updated_at": None}:
            publish_store.put_json("record.json", record)
        result["scored_matches"] = record["summary"].get("overall", {}).get("scored", 0)
        return result
    run_id = forecast_id(now)
    attempt = runs / run_id
    impact_state = data_store.get_json("state/impacts.json", {"schema_version": 1, "matches": {}})
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
        documents.append(
            update_impact_state(
                derive_forecast(
                    json.loads((archive / "forecast.json").read_text()),
                    run_id,
                    public_model_version=policy["product"]["model_version"],
                ),
                impact_state,
            )
        )
    if not documents:
        result.update(status="failed", failures=failures, attempt=str(attempt))
        write_immutable(attempt / "pipeline.json", json_bytes(result))
        sync_tree(attempt, data_store, f"runs/forecasts/{run_id}")
        return result
    result["private_sync"] = sync_tree(attempt, data_store, f"runs/forecasts/{run_id}")
    current = publish_documents(publish_store, documents, policy)
    record = update_record(publish_store.get_json("record.json"), documents, outcomes, policy)
    publish_store.put_json("record.json", record)
    for document in documents:
        result["published"].append(f"{document['competition_id']}/{document['forecast_id']}")
    result.update(
        status="partial" if failures else "ok",
        failures=failures,
        attempt=str(attempt),
        run_id=run_id,
        current_forecasts=len(current["forecasts"]),
        scored_matches=record["summary"].get("overall", {}).get("scored", 0),
    )
    write_immutable(attempt / "pipeline.json", json_bytes(result))
    competition_state = state.setdefault("competitions", {})
    for document in documents:
        competition_state[document["competition_id"]] = {
            "fingerprint": fingerprints[document["competition_id"]],
            "published_at": now.isoformat(),
            "forecast_id": document["forecast_id"],
        }
    data_store.put_json("state/forecast.json", state)
    data_store.put_json("state/impacts.json", impact_state)
    sync_tree(attempt, data_store, f"runs/forecasts/{run_id}")
    return result
