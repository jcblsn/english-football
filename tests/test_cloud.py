import hashlib
import io
import json
from datetime import UTC, datetime

import pytest

from epl_forecast.cloud import (
    collection_state,
    compact_canonical,
    compaction_due,
    manifest_state,
    sync_data,
    update_state,
)
from epl_forecast.datasets import Dataset, publish
from epl_forecast.storage import ConditionalWriteFailed


class Store:
    def __init__(self, directory=None):
        self.objects = {}
        self.directory = directory
        self.before_conditional_write = None

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

    def get_json_versioned(self, key, default=None):
        if key not in self.objects:
            return default, None
        return json.loads(self.objects[key]), hashlib.sha256(self.objects[key]).hexdigest()

    def put_json_if(self, key, value, version):
        if self.before_conditional_write is not None:
            hook, self.before_conditional_write = self.before_conditional_write, None
            hook(key)
        current = hashlib.sha256(self.objects[key]).hexdigest() if key in self.objects else None
        if current != version:
            raise ConditionalWriteFailed(key)
        self.put_json(key, value)

    def download(self, key, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.objects[key])

    def uri(self, key):
        return str(self.directory / key)

    def configure_duckdb(self, connection):
        pass


def seeded_store(directory):
    """A fake R2 bucket whose canonical catalog holds every batch published in the directory."""
    store = Store(directory)
    manifests = [
        json.loads(path.read_text()) for path in sorted(directory.glob("manifests/*.json"))
    ]
    store.put_json("state/manifests.json", manifest_state(manifests))
    return store


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


def test_a_concurrent_catalog_update_is_kept_after_a_retry():
    store = Store()
    store.put_json("state/manifests.json", manifest_state([{"batch_id": "old"}]))

    def other_writer(key):
        current = store.get_json(key)
        store.put_json(key, manifest_state([*current["manifests"], {"batch_id": "other"}]))

    store.before_conditional_write = other_writer
    result = update_state(
        store,
        "state/manifests.json",
        lambda current: manifest_state([*current["manifests"], {"batch_id": "mine"}]),
    )
    batches = {batch["batch_id"] for batch in store.get_json("state/manifests.json")["manifests"]}
    assert batches == {"old", "other", "mine"}
    assert result == store.get_json("state/manifests.json")


def test_a_state_update_stops_after_repeated_conflicts(monkeypatch):
    store = Store()

    def always_conflict(key, value, version):
        raise ConditionalWriteFailed(key)

    monkeypatch.setattr(store, "put_json_if", always_conflict)
    with pytest.raises(ConditionalWriteFailed, match="changed on each"):
        update_state(store, "state/collection.json", lambda current: {"latest_by_url": {"a": 1}})


def test_compaction_keeps_a_batch_that_arrives_during_compaction(tmp_path):
    root = tmp_path / "source"
    common = {"provider": "test", "evidence_basis": "captured", "context": {}}
    team = {"team_id": "arsenal", "name": "Arsenal"}
    publish(
        root,
        {**common, "retrieved_at": "2026-09-13T12:00:00+00:00", "source_sha256": "a" * 64},
        {"teams": [team]},
    )
    store = seeded_store(root)
    late = {"batch_id": "late", "request": {"retrieved_at": "2026-09-14T12:00:00+00:00"}}

    def collection_during_compaction(key):
        current = store.get_json(key)
        store.put_json(key, manifest_state([*current["manifests"], late]))

    store.before_conditional_write = collection_during_compaction
    result = compact_canonical(store)
    batches = [batch["batch_id"] for batch in store.get_json("state/manifests.json")["manifests"]]
    assert sorted(batches) == sorted([result["batch_id"], "late"])


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
    store = seeded_store(root)
    result = compact_canonical(store)
    manifest = json.loads(store.objects[f"manifests/{result['batch_id']}.json"])
    compacted = tmp_path / "compacted"
    for file in manifest["files"]:
        path = compacted / file["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(store.objects[file["path"]])
    data = Dataset(
        datetime(2026, 9, 13, 18, tzinfo=UTC),
        workspace=compacted,
        manifests=[manifest],
        store=None,
    )
    try:
        assert data.rows("SELECT home_odds FROM odds") == [{"home_odds": 2.0}]
    finally:
        data.close()
    repeated = compact_canonical(store)
    assert repeated["rows"] == result["rows"]


def test_compaction_keeps_the_snapshots_that_select_the_evidence(tmp_path):
    from epl_forecast.personnel import Evidence, load_evidence, team_continuity
    from epl_forecast.snapshots import SQUAD, snapshot

    root = tmp_path / "source"
    common = {"provider": "api_football", "evidence_basis": "captured", "context": {}}
    previous = [f"match-{number}" for number in range(8)]
    appearances = [
        {
            "match_id": match_id,
            "player_id": f"p{player}",
            "team_id": "arsenal",
            "competition_id": "eng-premier-league",
            "season_id": "2026-2027",
            "kickoff_time": f"2026-08-{number + 1:02d}T12:00:00+00:00",
            "starts": 1,
            "minutes": 90,
        }
        for number, match_id in enumerate(previous)
        for player in range(11)
    ]

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
            "appearances": appearances,
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

    def personnel_at(directory, manifests, cutoff):
        data = Dataset(cutoff, workspace=directory, manifests=manifests, store=None)
        try:
            evidence = Evidence(cutoff, **load_evidence(data, ["2026-2027"]))
            estimate = team_continuity(
                evidence,
                "arsenal",
                "target",
                "eng-premier-league",
                previous,
            )
            return evidence.squads, estimate
        finally:
            data.close()

    before = datetime(2026, 9, 13, 18, tzinfo=UTC)
    after = datetime(2026, 9, 14, 18, tzinfo=UTC)
    source_before = personnel_at(root, None, before)
    source_after = personnel_at(root, None, after)
    assert source_before[0] == {"arsenal": {"p1"}}
    assert source_after[0] == {"arsenal": set()}

    store = seeded_store(root)
    result = compact_canonical(store)
    manifest = json.loads(store.objects[f"manifests/{result['batch_id']}.json"])
    compacted = tmp_path / "compacted"
    for file in manifest["files"]:
        path = compacted / file["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(store.objects[file["path"]])
    # Compaction collapses the request contexts, so only a canonical row can still say that
    # the later response covered this scope and named nobody. A reader of the compacted
    # history must reach the same squad at the same cutoff as a reader of the source.
    assert personnel_at(compacted, [manifest], before) == source_before
    assert personnel_at(compacted, [manifest], after) == source_after


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
    monkeypatch.setattr(collection, "ENTRY_SOURCE_COMPETITIONS", {})
    for module in (collection.fpl, collection.football_data, collection.understat_ingest):
        monkeypatch.setattr(module, "ingest", ingest)
    monkeypatch.setattr(
        collection.kalshi, "collect", lambda *args, **kwargs: {"reused": True, "errors": []}
    )
    monkeypatch.setattr(capture, "urlopen", lambda *args, **kwargs: Response(b"{}"))
    store = Store(tmp_path / "remote")

    collect_and_sync(tmp_path / "incremental", store)
    assert len(store.get_json("state/manifests.json")["manifests"]) == 3
    compact_canonical(store)
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


def test_kalshi_error_blocks_the_unchanged_shortcut_until_a_retry(tmp_path, monkeypatch):
    """A failed daily Kalshi attempt stays due: a later run must send requests again."""
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

    monkeypatch.setattr(collection.api, "LEAGUES", {})
    monkeypatch.setattr(collection, "ENTRY_SOURCE_COMPETITIONS", {})
    for module in (collection.fpl, collection.football_data, collection.understat_ingest):
        monkeypatch.setattr(module, "ingest", ingest)
    monkeypatch.setattr(
        collection.kalshi,
        "collect",
        lambda *args, **kwargs: {
            "reused": False,
            "errors": ["Cannot retrieve https://example.test/kalshi: simulated outage"],
            "observed_markets": 0,
            "series": [],
            "season_id": "2026-2027",
        },
    )
    monkeypatch.setattr(capture, "urlopen", lambda *args, **kwargs: Response(b"{}"))
    store = Store(tmp_path / "remote")

    report, synced = collect_and_sync(tmp_path / "kalshi-failed", store)
    assert report["status"] == "partial"
    assert report["kalshi"]["reused"] is False

    monkeypatch.setattr(
        collection.kalshi, "collect", lambda *args, **kwargs: {"reused": True, "errors": []}
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("A reused Kalshi day must not send a request")

    monkeypatch.setattr(capture, "urlopen", forbidden)
    report, synced = collect_and_sync(tmp_path / "kalshi-reused", store)
    assert report["kalshi"] == {"reused": True, "errors": []}


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
    monkeypatch.setattr(collection, "ENTRY_SOURCE_COMPETITIONS", {})
    for module in (collection.fpl, collection.football_data, collection.understat_ingest):
        monkeypatch.setattr(module, "ingest", ingest)
    monkeypatch.setattr(
        collection.kalshi, "collect", lambda *args, **kwargs: {"reused": True, "errors": []}
    )
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
