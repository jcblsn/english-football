import json
from datetime import UTC, datetime
from threading import Barrier
from types import SimpleNamespace

import pytest
from test_publication import sample_forecast, sample_run

from epl_forecast import pipeline
from epl_forecast.pipeline import due, forecast_id, production_fingerprint
from epl_forecast.storage import ConditionalWriteFailed

NOW = datetime(2026, 9, 10, 22, 43, 3, tzinfo=UTC)


def test_forecast_id_is_a_sortable_second():
    assert forecast_id(NOW) == "2026-09-10T224303Z"


class Completed:
    def __init__(self, returncode):
        self.returncode, self.stdout, self.stderr = returncode, "", "forecast failed"


class FakeDataset:
    def fixtures(self):
        return []

    def close(self):
        pass


class Store:
    def __init__(self, name="store", writes=None):
        self.objects = {}
        self.versions = {}
        self.name = name
        self.writes = writes if writes is not None else []

    def keys(self, prefix=""):
        return (key for key in self.objects if key.startswith(prefix))

    def identities(self, keys):
        return {key: self.versions.get(key) for key in keys}

    def upload(self, source, key, immutable=False):
        payload = source.read_bytes()
        if immutable and key in self.objects and self.objects[key] != payload:
            raise ValueError(key)
        self.objects[key] = payload
        self.versions[key] = str(int(self.versions.get(key, "0")) + 1)
        self.writes.append((self.name, key, immutable))

    def download(self, key, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.objects[key])

    def get_json(self, key, default=None):
        return self.objects.get(key, default)

    def put_json(self, key, value, immutable=False):
        if immutable and key in self.objects and self.objects[key] != value:
            raise ValueError(key)
        self.objects[key] = value
        self.versions[key] = str(int(self.versions.get(key, "0")) + 1)
        self.writes.append((self.name, key, immutable))

    def get_json_versioned(self, key, default=None):
        return self.objects.get(key, default), self.versions.get(key)

    def put_json_if(self, key, value, version):
        if self.versions.get(key) != version:
            raise ConditionalWriteFailed(key)
        self.put_json(key, value)

    def exists(self, key):
        return key in self.objects


def prepared_snapshot(workspace):
    return SimpleNamespace(
        data=FakeDataset(),
        database=workspace / "canonical.duckdb",
        manifest_path=workspace / "canonical.manifest.json",
        manifest={},
    )


def disable_fit_store(monkeypatch):
    monkeypatch.setattr(pipeline, "prepare_fit_store", lambda *args: None)
    monkeypatch.setattr(pipeline, "commit_fit_store", lambda *args: {})


def install_fake_snapshot(monkeypatch, calls):
    class Source:
        def close(self):
            pass

    class Snapshot:
        def __init__(self, database, cutoff, manifest_path):
            manifest = json.loads(manifest_path.read_text())
            self.source_revision = manifest["source_revision"]

        def close(self):
            pass

    def create(source, destination, source_revision):
        calls.append(source_revision)
        destination.write_bytes(b"snapshot")
        manifest = {
            "schema_version": 1,
            "source_revision": source_revision,
            "data_revision": "data-1",
            "database_bytes": len(b"snapshot"),
            "database_sha256": pipeline.file_hash(destination),
            "created_at": NOW.isoformat(),
        }
        pipeline.snapshot_manifest_path(destination).write_text(json.dumps(manifest))
        return manifest

    monkeypatch.setattr(pipeline, "Dataset", lambda *args, **kwargs: Source())
    monkeypatch.setattr(pipeline, "create_snapshot", create)
    monkeypatch.setattr(pipeline, "SnapshotDataset", Snapshot)


def test_a_division_that_fails_does_not_hold_back_the_others(tmp_path, monkeypatch, capsys):
    """One division that cannot be forecast leaves the others published."""
    started = Barrier(4)

    def fake_forecast(league, cutoff, output, simulations, **kwargs):
        started.wait(timeout=1)
        if league == "eng-championship":
            return Completed(1)
        output.mkdir(parents=True, exist_ok=True)
        (output / "forecast.json").write_text(json.dumps(sample_forecast(competition=league)))
        (output / "run.json").write_text(json.dumps(sample_run()))
        return Completed(0)

    def fake_verify(archive, output):
        output.mkdir(parents=True, exist_ok=True)
        (output / "verification.json").write_text(
            json.dumps({"archives": {str(archive): {"checks": [], "failures": 0}}})
        )
        return Completed(0)

    monkeypatch.setattr(pipeline, "run_forecast", fake_forecast)
    monkeypatch.setattr(pipeline, "verify_archive", fake_verify)
    disable_fit_store(monkeypatch)
    monkeypatch.setattr(
        pipeline,
        "prepare_operation_snapshot",
        lambda cutoff, store, workspace: prepared_snapshot(workspace),
    )
    monkeypatch.setattr(
        pipeline, "information_fingerprint", lambda dataset, competition: "fingerprint"
    )
    monkeypatch.setattr(pipeline, "realized_outcomes", lambda fixtures: {})
    data_store, publish_store = Store(), Store()
    result = pipeline.operate(
        force=True,
        collect_first=False,
        data_store=data_store,
        publish_store=publish_store,
    )
    assert result["status"] == "partial"
    assert [row.split("/")[0] for row in result["published"]] == [
        "eng-premier-league",
        "eng-league-one",
        "eng-league-two",
    ]
    assert [failure["league"] for failure in result["failures"]] == ["eng-championship"]
    state = data_store.objects["state/forecast.json"]
    assert set(state["competitions"]) == {
        "eng-premier-league",
        "eng-league-one",
        "eng-league-two",
    }
    assert "eng-championship" not in state["competitions"]
    events = [json.loads(line)["event"] for line in capsys.readouterr().out.splitlines()]
    assert events[0] == "operation_started"
    assert events.count("forecast_started") == 4
    assert "forecast_failed" in events
    assert events[-1] == "operation_finished"


def test_only_an_effective_change_makes_a_division_due():
    state = {"competitions": {"eng-premier-league": {"fingerprint": "abc"}}}
    assert not due(state, "abc", "eng-premier-league")
    assert due(state, "def", "eng-premier-league")
    assert due(state, "abc", "eng-championship")
    assert due({}, "abc", "eng-premier-league")


def test_forecast_code_and_configuration_are_part_of_the_fingerprint(tmp_path, monkeypatch):
    source = tmp_path / "forecast.py"
    config = tmp_path / "product.toml"
    source.write_text("VERSION = 1\n")
    config.write_text('model = "v0.0"\n')
    monkeypatch.setattr(pipeline, "MODEL_CODE", (source, config))
    first = production_fingerprint("data", "v0.0")
    config.write_text('model = "v0.1"\n')
    assert production_fingerprint("data", "v0.0") != first


def test_a_public_model_version_change_makes_every_division_due():
    assert production_fingerprint("data", "v0.1") != production_fingerprint("data", "v0.0")


def test_fit_store_uses_verified_immutable_object_and_conditional_pointer(tmp_path):
    store = Store()
    source = tmp_path / "source.duckdb"
    source.write_bytes(b"checkpoint")
    assert pipeline.prepare_fit_store(store, "eng-championship", tmp_path / "missing") is None
    pointer = pipeline.commit_fit_store(store, "eng-championship", source, None)
    destination = tmp_path / "restored.duckdb"
    version = pipeline.prepare_fit_store(store, "eng-championship", destination)
    assert destination.read_bytes() == b"checkpoint"
    assert version == store.versions["state/fits/eng-championship.json"]
    assert pointer["database_key"].startswith("fits/eng-championship/")
    with pytest.raises(ConditionalWriteFailed):
        pipeline.commit_fit_store(store, "eng-championship", source, None)


def test_snapshot_pointer_commits_after_immutable_objects_and_restores(tmp_path, monkeypatch):
    store = Store()
    store.versions["state/manifests.json"] = "source-1"
    calls = []
    install_fake_snapshot(monkeypatch, calls)
    first = tmp_path / "first"
    first.mkdir()
    prepared = pipeline.prepare_operation_snapshot(NOW, store, first)
    prepared.data.close()
    keys = [key for _, key, _ in store.writes]
    assert keys[-1] == pipeline.SNAPSHOT_POINTER
    assert keys.index("snapshots/data-1.duckdb") < keys.index(pipeline.SNAPSHOT_POINTER)
    assert keys.index("snapshots/data-1.manifest.json") < keys.index(pipeline.SNAPSHOT_POINTER)
    assert calls == ["source-1"]

    second = tmp_path / "second"
    second.mkdir()
    restored = pipeline.prepare_operation_snapshot(NOW, store, second)
    restored.data.close()
    assert restored.database.read_bytes() == b"snapshot"
    assert calls == ["source-1"]


def test_snapshot_pointer_failure_keeps_last_good_revision(tmp_path, monkeypatch):
    class FailingStore(Store):
        def put_json_if(self, key, value, version):
            raise RuntimeError("pointer unavailable")

    store = FailingStore()
    store.versions["state/manifests.json"] = "source-2"
    old = {"source_revision": "source-1"}
    store.put_json(pipeline.SNAPSHOT_POINTER, old)
    install_fake_snapshot(monkeypatch, [])
    workspace = tmp_path / "failure"
    workspace.mkdir()
    with pytest.raises(RuntimeError, match="pointer unavailable"):
        pipeline.prepare_operation_snapshot(NOW, store, workspace)
    assert store.objects[pipeline.SNAPSHOT_POINTER] == old


def test_snapshot_commit_conflict_restores_winning_revision(tmp_path, monkeypatch):
    class ConflictStore(Store):
        def put_json_if(self, key, value, version):
            super().put_json_if(key, value, version)
            raise ConditionalWriteFailed(key)

    store = ConflictStore()
    store.versions["state/manifests.json"] = "source-1"
    calls = []
    install_fake_snapshot(monkeypatch, calls)
    workspace = tmp_path / "conflict"
    workspace.mkdir()
    prepared = pipeline.prepare_operation_snapshot(NOW, store, workspace)
    prepared.data.close()
    assert prepared.database.read_bytes() == b"snapshot"
    assert store.objects[pipeline.SNAPSHOT_POINTER]["source_revision"] == "source-1"
    assert calls == ["source-1"]


def test_r2_operation_writes_private_runs_before_public_index(tmp_path, monkeypatch):
    def fake_forecast(league, cutoff, output, simulations, **kwargs):
        output.mkdir(parents=True, exist_ok=True)
        (output / "forecast.json").write_text(json.dumps(sample_forecast(competition=league)))
        (output / "run.json").write_text(json.dumps(sample_run()))
        return Completed(0)

    def fake_verify(archive, output):
        output.mkdir(parents=True, exist_ok=True)
        (output / "verification.json").write_text(
            json.dumps({"archives": {str(archive): {"checks": [], "failures": 0}}})
        )
        return Completed(0)

    monkeypatch.setattr(pipeline, "run_forecast", fake_forecast)
    monkeypatch.setattr(pipeline, "verify_archive", fake_verify)
    disable_fit_store(monkeypatch)
    monkeypatch.setattr(
        pipeline,
        "prepare_operation_snapshot",
        lambda cutoff, store, workspace: prepared_snapshot(workspace),
    )
    monkeypatch.setattr(
        pipeline, "information_fingerprint", lambda dataset, competition: "fingerprint"
    )
    monkeypatch.setattr(pipeline, "realized_outcomes", lambda fixtures: {})
    writes = []
    data_store, publish_store = Store("private", writes), Store("public", writes)
    result = pipeline.operate(
        force=True,
        collect_first=False,
        data_store=data_store,
        publish_store=publish_store,
    )
    assert result["status"] == "ok"
    assert set(data_store.objects["state/forecast.json"]["competitions"]) == set(pipeline.LEAGUES)
    assert "forecasts/current.json" in publish_store.objects
    assert "record.json" in publish_store.objects
    assert any(key.startswith("runs/forecasts/") for key in data_store.objects)
    private_run = next(
        index
        for index, (store, key, _) in enumerate(writes)
        if store == "private" and key.startswith("runs/forecasts/")
    )
    current_pointer = next(
        index
        for index, (store, key, _) in enumerate(writes)
        if store == "public" and key == "forecasts/current.json"
    )
    assert private_run < current_pointer
