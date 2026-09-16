import io
import json
from datetime import UTC, datetime

from epl_forecast.cloud import (
    collection_state,
    compact_canonical,
    compaction_due,
    manifest_state,
    sync_data,
)
from epl_forecast.datasets import Dataset, publish


class Store:
    def __init__(self, directory=None):
        self.objects = {}
        self.directory = directory

    def keys(self, prefix=""):
        return (key for key in self.objects if key.startswith(prefix))

    def exists(self, key):
        return key in self.objects

    def upload(self, source, key, immutable=False):
        payload = source.read_bytes()
        if immutable and key in self.objects and self.objects[key] != payload:
            raise ValueError(key)
        self.objects[key] = payload
        if self.directory:
            path = self.directory / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)

    def get_json(self, key, default=None):
        return json.loads(self.objects[key]) if key in self.objects else default

    def put_json(self, key, value, immutable=False):
        self.objects[key] = json.dumps(value).encode()

    def download(self, key, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.objects[key])

    def uri(self, key):
        return str(self.directory / key)

    def configure_duckdb(self, connection):
        pass


def request(url, retrieved_at, source="a"):
    return {
        "provider": "test",
        "url": url,
        "retrieved_at": retrieved_at,
        "evidence_basis": "captured",
        "source_sha256": source * 64,
        "raw_path": f"raw/test/{source}.json",
        "context": {},
    }


def test_compact_collection_state_keeps_only_the_latest_request_for_each_url():
    old = request("https://example.test/a", "2026-09-13T12:00:00+00:00")
    new = request("https://example.test/a", "2026-09-14T12:00:00+00:00", "b")
    other = request("https://example.test/b", "2026-09-13T12:00:00+00:00", "c")
    state = collection_state([new, other, old])
    assert set(state["latest_by_url"]) == {old["url"], other["url"]}
    assert state["latest_by_url"][old["url"]] == new


def test_manifest_state_replaces_a_batch_without_duplicating_it():
    assert manifest_state([{"batch_id": "one", "rows": 1}, {"batch_id": "one", "rows": 2}]) == {
        "schema_version": 1,
        "manifests": [{"batch_id": "one", "rows": 2}],
    }


def test_data_sync_writes_objects_before_mutable_state(tmp_path):
    record = request("https://example.test/a", "2026-09-14T12:00:00+00:00")
    for name, value in (
        ("raw/test/a.json", b"raw"),
        ("requests/a.json", json.dumps(record).encode()),
        ("parquet/teams/a.parquet", b"parquet"),
        (
            "manifests/a.json",
            json.dumps(
                {
                    "batch_id": "a",
                    "files": [{"table": "teams", "path": "parquet/teams/a.parquet"}],
                }
            ).encode(),
        ),
        ("audits/collection.json", b"{}"),
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    store = Store()
    result = sync_data(
        tmp_path,
        store,
        manifest_paths=[tmp_path / "manifests/a.json"],
        request_paths=[tmp_path / "requests/a.json"],
    )
    assert result == {"uploaded": 4, "audits": 1, "manifests": 1, "request_urls": 1}
    assert set(store.objects) == {
        "raw/test/a.json",
        "requests/a.json",
        "parquet/teams/a.parquet",
        "manifests/a.json",
        "audits/collection.json",
        "state/manifests.json",
        "state/collection.json",
    }


def test_routine_data_sync_reads_only_the_current_collection(tmp_path):
    old = request("https://example.test/old", "2026-09-13T12:00:00+00:00")
    current = request("https://example.test/current", "2026-09-14T12:00:00+00:00", "b")
    paths = []
    for name, record in (("old", old), ("current", current)):
        raw = tmp_path / record["raw_path"]
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(name.encode())
        path = tmp_path / "requests" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record))
        paths.append(path)
    store = Store()

    result = sync_data(tmp_path, store, manifest_paths=[], request_paths=[paths[1]])

    assert result["uploaded"] == 2
    assert "requests/current.json" in store.objects
    assert "requests/old.json" not in store.objects
    assert set(store.get_json("state/collection.json")["latest_by_url"]) == {current["url"]}


def test_compaction_is_due_after_enough_incremental_batches():
    store = Store()
    store.put_json(
        "state/manifests.json",
        manifest_state(
            [
                {"batch_id": "base", "covers_history": True},
                {"batch_id": "one"},
                {"batch_id": "two"},
            ]
        ),
    )
    assert compaction_due(store, 2)
    assert not compaction_due(store, 3)


def test_compaction_preserves_row_level_cutoffs(tmp_path):
    root = tmp_path / "source"
    common = {
        "provider": "test",
        "evidence_basis": "captured",
        "source_sha256": "a" * 64,
        "context": {},
    }
    odds = {
        "match_id": "match",
        "competition_id": "eng-premier-league",
        "season_id": "2026-2027",
        "family": "market_average_preclosing",
        "home_odds": 2,
        "draw_odds": 3,
        "away_odds": 4,
    }
    publish(
        root,
        {**common, "retrieved_at": "2026-09-13T12:00:00+00:00"},
        {"odds": [odds]},
    )
    publish(
        root,
        {
            **common,
            "retrieved_at": "2026-09-14T12:00:00+00:00",
            "source_sha256": "b" * 64,
        },
        {"odds": [{**odds, "home_odds": 2.5}]},
    )
    store = Store(tmp_path / "remote")
    result = compact_canonical(root, store)
    manifest = json.loads(store.objects[f"manifests/{result['batch_id']}.json"])
    compacted = tmp_path / "compacted"
    for file in manifest["files"]:
        path = compacted / file["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(store.objects[file["path"]])
    data = Dataset(
        compacted,
        datetime(2026, 9, 13, 18, tzinfo=UTC),
        manifests=[manifest],
        store=None,
    )
    try:
        assert data.rows("SELECT home_odds FROM odds") == [{"home_odds": 2.0}]
    finally:
        data.close()
    repeated = compact_canonical(root, store)
    assert repeated["rows"] == result["rows"]


def test_compaction_keeps_the_snapshots_that_select_the_evidence(tmp_path):
    from epl_forecast.personnel import Evidence, load_evidence
    from epl_forecast.snapshots import SQUAD, snapshot

    root = tmp_path / "source"
    common = {"provider": "api_football", "evidence_basis": "captured", "context": {}}

    def squad_snapshot(row_count):
        return snapshot(
            SQUAD,
            "arsenal",
            endpoint="players/squads",
            row_count=row_count,
            competition_id="eng-premier-league",
            season_id="2026-2027",
            team_id="arsenal",
        )

    publish(
        root,
        {**common, "retrieved_at": "2026-09-13T12:00:00+00:00", "source_sha256": "a" * 64},
        {
            "memberships": [
                {
                    "player_id": "p1",
                    "team_id": "arsenal",
                    "season_id": "2026-2027",
                    "competition_id": "eng-premier-league",
                    "basis": "captured_squad",
                    "scope": "42",
                }
            ],
            "source_snapshots": [squad_snapshot(1)],
        },
    )
    # The provider later answers the same scope with nobody, so this batch publishes a
    # snapshot and no squad rows at all.
    publish(
        root,
        {**common, "retrieved_at": "2026-09-14T12:00:00+00:00", "source_sha256": "b" * 64},
        {"source_snapshots": [squad_snapshot(0)]},
    )

    def squads_at(directory, manifests, cutoff):
        data = Dataset(directory, cutoff, manifests=manifests, store=None)
        try:
            return Evidence(cutoff, **load_evidence(data, ["2026-2027"])).squads
        finally:
            data.close()

    before = datetime(2026, 9, 13, 18, tzinfo=UTC)
    after = datetime(2026, 9, 14, 18, tzinfo=UTC)
    assert squads_at(root, None, before) == {"arsenal": {"p1"}}
    assert squads_at(root, None, after) == {"arsenal": set()}

    store = Store(tmp_path / "remote")
    result = compact_canonical(root, store)
    manifest = json.loads(store.objects[f"manifests/{result['batch_id']}.json"])
    compacted = tmp_path / "compacted"
    for file in manifest["files"]:
        path = compacted / file["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(store.objects[file["path"]])
    # Compaction collapses the request contexts, so only a canonical row can still say that
    # the later response covered this scope and named nobody. A reader of the compacted
    # history must reach the same squad at the same cutoff as a reader of the source.
    assert squads_at(compacted, [manifest], before) == {"arsenal": {"p1"}}
    assert squads_at(compacted, [manifest], after) == {"arsenal": set()}


def test_unchanged_collection_after_compaction_keeps_the_catalog_compact(tmp_path, monkeypatch):
    from epl_forecast.data import capture
    from epl_forecast.data import collect as collection
    from epl_forecast.pipeline import collect_and_sync

    class Response(io.BytesIO):
        headers = {}

    def ingest(root, record, payload):
        request = {
            key: record[key]
            for key in ("provider", "retrieved_at", "evidence_basis", "source_sha256", "context")
        }
        publish(root, request, {"teams": [{"team_id": record["provider"], "name": record["url"]}]})

    def forbidden(*args, **kwargs):
        raise AssertionError("A retained response inside its interval must not be requested")

    monkeypatch.setattr(collection.api, "LEAGUES", {})
    monkeypatch.setattr(collection, "COMPETITIONS", {})
    monkeypatch.setattr(collection, "ENTRY_SOURCE_COMPETITIONS", {})
    for module in (collection.fpl, collection.football_data, collection.understat_ingest):
        monkeypatch.setattr(module, "ingest", ingest)
    monkeypatch.setattr(capture, "urlopen", lambda *args, **kwargs: Response(b"{}"))
    store = Store(tmp_path / "remote")

    collect_and_sync(tmp_path / "incremental", store)
    assert len(store.get_json("state/manifests.json")["manifests"]) == 3
    compact_canonical(tmp_path / "maintenance", store)
    catalog = store.objects["state/manifests.json"]
    requests = store.objects["state/collection.json"]
    assert len(json.loads(catalog)["manifests"]) == 1

    monkeypatch.setattr(capture, "urlopen", forbidden)
    report, synced = collect_and_sync(tmp_path / "unchanged", store)

    assert report["errors"] == []
    assert synced["uploaded"] == synced["audits"] == 0
    assert store.objects["state/manifests.json"] == catalog
    assert store.objects["state/collection.json"] == requests
    assert not compaction_due(store, 1)


def test_api_football_usage_records_only_runs_that_call_the_provider(tmp_path, monkeypatch):
    from epl_forecast.data import capture
    from epl_forecast.data import collect as collection
    from epl_forecast.pipeline import collect_and_sync

    class Response(io.BytesIO):
        headers = {"x-ratelimit-requests-limit": "7500", "x-ratelimit-requests-remaining": "7499"}

    def ingest(root, record, payload):
        request = {
            key: record[key]
            for key in ("provider", "retrieved_at", "evidence_basis", "source_sha256", "context")
        }
        publish(root, request, {"teams": [{"team_id": record["provider"], "name": record["url"]}]})

    def fetch(request, **kwargs):
        if request.full_url.startswith(collection.api.BASE):
            return Response(b'{"errors":{"token":"invalid"},"response":[]}')
        return Response(b"{}")

    monkeypatch.setenv("API_FOOTBALL_KEY", "test-only-credential")
    monkeypatch.setattr(capture.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(collection.api, "LEAGUES", {39: "eng-premier-league"})
    monkeypatch.setattr(collection, "COMPETITIONS", {})
    monkeypatch.setattr(collection, "ENTRY_SOURCE_COMPETITIONS", {})
    for module in (collection.fpl, collection.football_data, collection.understat_ingest):
        monkeypatch.setattr(module, "ingest", ingest)
    monkeypatch.setattr(capture, "urlopen", fetch)
    store = Store(tmp_path / "remote")

    report, _ = collect_and_sync(tmp_path / "calling", store)
    records = [key for key in store.objects if key.startswith("audits/api_football/")]
    assert report["api_football"]["calls"] == 1
    assert len(records) == 1
    usage = json.loads(store.objects[records[0]])
    assert usage["calls"] == 1
    assert (usage["daily_limit"], usage["daily_remaining"]) == (7500, 7499)
    assert usage["status"] == "partial"

    monkeypatch.setattr(collection.api, "LEAGUES", {})
    report, synced = collect_and_sync(tmp_path / "quiet", store)
    assert report["api_football"] == {
        "calls": 0,
        "daily_limit": None,
        "daily_remaining": None,
        "observed_at": None,
    }
    assert synced["uploaded"] == 0 and synced["audits"] == 1
    assert not (tmp_path / "quiet" / "audits" / "api_football").exists()

    before = dict(store.objects)
    report, synced = collect_and_sync(tmp_path / "unchanged", store)
    assert synced["uploaded"] == synced["audits"] == 0
    assert store.objects == before
