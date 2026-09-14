import json
from datetime import UTC, datetime

from test_publication import sample_forecast, sample_run

from epl_forecast import pipeline
from epl_forecast.pipeline import due, snapshot_id

NOW = datetime(2026, 9, 10, 22, 43, 3, tzinfo=UTC)


def test_snapshot_id_is_a_sortable_second():
    assert snapshot_id(NOW) == "2026-09-10T224303Z"


class Completed:
    def __init__(self, returncode):
        self.returncode, self.stdout, self.stderr = returncode, "", "forecast failed"


class FakeDataset:
    def fixtures(self):
        return []

    def close(self):
        pass


class Store:
    def __init__(self):
        self.objects = {}

    def keys(self, prefix=""):
        return (key for key in self.objects if key.startswith(prefix))

    def upload(self, source, key, immutable=False):
        payload = source.read_bytes()
        if immutable and key in self.objects and self.objects[key] != payload:
            raise ValueError(key)
        self.objects[key] = payload

    def get_json(self, key, default=None):
        return self.objects.get(key, default)

    def put_json(self, key, value, immutable=False):
        if immutable and key in self.objects and self.objects[key] != value:
            raise ValueError(key)
        self.objects[key] = value

    def exists(self, key):
        return key in self.objects


def test_a_division_that_fails_does_not_hold_back_the_others(tmp_path, monkeypatch):
    """One division that cannot be forecast leaves the others published."""

    def fake_forecast(data, league, cutoff, output, simulations):
        if league == "eng-championship":
            return Completed(1)
        output.mkdir(parents=True, exist_ok=True)
        (output / "forecast.json").write_text(json.dumps(sample_forecast(competition=league)))
        (output / "run.json").write_text(json.dumps(sample_run()))
        return Completed(0)

    def fake_verify(data, archive, output):
        output.mkdir(parents=True, exist_ok=True)
        (output / "verification.json").write_text(
            json.dumps({"archives": {str(archive): {"checks": [], "failures": 0}}})
        )
        return Completed(0)

    monkeypatch.setattr(pipeline, "run_forecast", fake_forecast)
    monkeypatch.setattr(pipeline, "verify_archive", fake_verify)
    monkeypatch.setattr(pipeline, "Dataset", lambda *args, **kwargs: FakeDataset())
    monkeypatch.setattr(pipeline, "information_fingerprint", lambda dataset: "fingerprint")
    monkeypatch.setattr(pipeline, "realized_outcomes", lambda fixtures: {})
    runs = tmp_path / "runs"
    result = pipeline.operate(
        data=tmp_path / "data",
        site=tmp_path / "site",
        runs=runs,
        force=True,
        collect_first=False,
    )
    assert result["status"] == "partial"
    assert [row.split("/")[1] for row in result["published"]] == [
        "eng-premier-league",
        "eng-league-one",
        "eng-league-two",
    ]
    assert [failure["league"] for failure in result["failures"]] == ["eng-championship"]
    state = json.loads((runs / "state.json").read_text())
    assert set(state["competitions"]) == {
        "eng-premier-league",
        "eng-league-one",
        "eng-league-two",
    }
    assert "eng-championship" not in state["competitions"]


def test_only_an_effective_change_makes_a_division_due():
    state = {"competitions": {"eng-premier-league": {"fingerprint": "abc"}}}
    assert not due(state, "abc", "eng-premier-league")
    assert due(state, "def", "eng-premier-league")
    assert due(state, "abc", "eng-championship")
    assert due({}, "abc", "eng-premier-league")


def test_r2_operation_writes_private_runs_before_public_index(tmp_path, monkeypatch):
    def fake_forecast(data, league, cutoff, output, simulations):
        output.mkdir(parents=True, exist_ok=True)
        (output / "forecast.json").write_text(json.dumps(sample_forecast(competition=league)))
        (output / "run.json").write_text(json.dumps(sample_run()))
        return Completed(0)

    def fake_verify(data, archive, output):
        output.mkdir(parents=True, exist_ok=True)
        (output / "verification.json").write_text(
            json.dumps({"archives": {str(archive): {"checks": [], "failures": 0}}})
        )
        return Completed(0)

    monkeypatch.setattr(pipeline, "run_forecast", fake_forecast)
    monkeypatch.setattr(pipeline, "verify_archive", fake_verify)
    monkeypatch.setattr(pipeline, "Dataset", lambda *args, **kwargs: FakeDataset())
    monkeypatch.setattr(pipeline, "information_fingerprint", lambda dataset: "fingerprint")
    monkeypatch.setattr(pipeline, "realized_outcomes", lambda fixtures: {})
    data_store, publish_store = Store(), Store()
    result = pipeline.operate(
        data=tmp_path / "data",
        site=tmp_path / "site",
        runs=tmp_path / "runs",
        force=True,
        collect_first=False,
        data_store=data_store,
        publish_store=publish_store,
    )
    assert result["status"] == "ok"
    assert set(data_store.objects["state/forecast.json"]["competitions"]) == set(pipeline.LEAGUES)
    assert "forecasts/index.json" in publish_store.objects
    assert "hindcasts/index.json" in publish_store.objects
    assert "record.json" in publish_store.objects
    assert any(key.startswith("runs/forecasts/") for key in data_store.objects)
