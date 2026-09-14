import json
from datetime import UTC, datetime

from epl_forecast.cloud import collection_state, compact_canonical, manifest_state, sync_data
from epl_forecast.datasets import Dataset, publish


class Store:
    def __init__(self, directory=None):
        self.objects = {}
        self.directory = directory

    def keys(self, prefix=""):
        return (key for key in self.objects if key.startswith(prefix))

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
        ("manifests/a.json", json.dumps({"batch_id": "a", "files": []}).encode()),
        ("audits/collection.json", b"{}"),
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    store = Store()
    result = sync_data(tmp_path, store)
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


def test_data_sync_does_not_expand_a_compact_catalog_with_cached_manifests(tmp_path):
    cached = {"batch_id": "cached", "files": [], "request": {}}
    path = tmp_path / "manifests/cached.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(cached))
    compact = {"batch_id": "compact", "covers_history": True, "files": []}
    store = Store()
    store.objects["manifests/cached.json"] = path.read_bytes()
    store.put_json("state/manifests.json", manifest_state([compact]))

    result = sync_data(tmp_path, store)

    assert result["uploaded"] == 0
    assert result["manifests"] == 1
    assert store.get_json("state/manifests.json") == manifest_state([compact])


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
