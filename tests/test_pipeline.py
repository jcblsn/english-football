import json
from datetime import UTC, datetime

from test_publication import sample_forecast, sample_run

from epl_forecast import pipeline
from epl_forecast.pipeline import due, forecast_id, production_fingerprint

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
        self.name = name
        self.writes = writes if writes is not None else []

    def keys(self, prefix=""):
        return (key for key in self.objects if key.startswith(prefix))

    def upload(self, source, key, immutable=False):
        payload = source.read_bytes()
        if immutable and key in self.objects and self.objects[key] != payload:
            raise ValueError(key)
        self.objects[key] = payload
        self.writes.append((self.name, key, immutable))

    def get_json(self, key, default=None):
        return self.objects.get(key, default)

    def put_json(self, key, value, immutable=False):
        if immutable and key in self.objects and self.objects[key] != value:
            raise ValueError(key)
        self.objects[key] = value
        self.writes.append((self.name, key, immutable))

    def exists(self, key):
        return key in self.objects


def test_a_division_that_fails_does_not_hold_back_the_others(tmp_path, monkeypatch, capsys):
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
    monkeypatch.setattr(
        pipeline, "information_fingerprint", lambda dataset, competition: "fingerprint"
    )
    monkeypatch.setattr(pipeline, "realized_outcomes", lambda fixtures: {})
    runs = tmp_path / "runs"
    data_store, publish_store = Store(), Store()
    result = pipeline.operate(
        data=tmp_path / "data",
        runs=runs,
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
    monkeypatch.setattr(
        pipeline, "information_fingerprint", lambda dataset, competition: "fingerprint"
    )
    monkeypatch.setattr(pipeline, "realized_outcomes", lambda fixtures: {})
    writes = []
    data_store, publish_store = Store("private", writes), Store("public", writes)
    result = pipeline.operate(
        data=tmp_path / "data",
        runs=tmp_path / "runs",
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
