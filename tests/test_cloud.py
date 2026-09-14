import json

from epl_forecast.cloud import collection_state, manifest_state, sync_data


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
        return json.loads(self.objects[key]) if key in self.objects else default

    def put_json(self, key, value, immutable=False):
        self.objects[key] = json.dumps(value).encode()


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
