import hashlib
import json
import os

import pytest

from epl_forecast.cloud import manifest_state
from epl_forecast.data import replay
from epl_forecast.data.capture import retain
from epl_forecast.datasets import Dataset, publish
from epl_forecast.storage import ConditionalWriteFailed, json_bytes


class Bucket:
    """A fake R2 bucket whose objects are files in one directory."""

    def __init__(self, directory):
        self.directory = directory
        self.before_conditional_write = None

    def keys(self, prefix=""):
        return sorted(
            path.relative_to(self.directory).as_posix()
            for path in self.directory.rglob("*")
            if path.is_file() and path.relative_to(self.directory).as_posix().startswith(prefix)
        )

    def get_bytes(self, key):
        return (self.directory / key).read_bytes()

    def get_json(self, key, default=None):
        path = self.directory / key
        return json.loads(path.read_text()) if path.exists() else default

    def download(self, key, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.get_bytes(key))

    def upload(self, source, key, immutable=False):
        path = self.directory / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(source.read_bytes())

    def put_json(self, key, value, immutable=False):
        path = self.directory / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(json_bytes(value))

    def get_json_versioned(self, key, default=None):
        path = self.directory / key
        if not path.exists():
            return default, None
        return json.loads(path.read_text()), hashlib.sha256(path.read_bytes()).hexdigest()

    def put_json_if(self, key, value, version):
        if self.before_conditional_write is not None:
            hook, self.before_conditional_write = self.before_conditional_write, None
            hook(key)
        path = self.directory / key
        current = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        if current != version:
            raise ConditionalWriteFailed(key)
        self.put_json(key, value)

    def uri(self, key):
        return str(self.directory / key)

    def configure_duckdb(self, connection):
        pass


SQUAD_CONTEXT = {
    "endpoint": "players/squads",
    "team": 42,
    "season_id": "2026-2027",
    "competition_id": "eng-premier-league",
}


def bucket_with_captures(tmp_path):
    """Two raw captures in R2, and a catalog that holds an older normalization of the history."""
    remote = tmp_path / "remote"
    body = {
        "response": [
            {
                "team": {"id": 42, "name": "Arsenal"},
                "players": [{"id": 1, "name": "Player One", "position": "Defender"}],
            }
        ]
    }
    squad = retain(
        remote,
        "api_football",
        "https://example.test/squads",
        json.dumps(body).encode(),
        "2026-09-08T10:00:00+00:00",
        "captured",
        SQUAD_CONTEXT,
    )
    retain(
        remote,
        "efl_rules",
        "https://example.test/rules",
        b"rules evidence",
        "2026-09-08T10:00:00+00:00",
        "captured",
    )
    old = publish(
        remote,
        {
            "provider": "test",
            "retrieved_at": "2026-09-01T00:00:00+00:00",
            "evidence_basis": "captured",
            "source_sha256": "f" * 64,
        },
        {"players": [{"player_id": "old-normalization", "name": "Old"}]},
    )
    bucket = Bucket(remote)
    bucket.put_json("state/manifests.json", manifest_state([old]))
    return bucket, squad


def player_ids(bucket):
    data = Dataset(store=bucket)
    try:
        return [row["player_id"] for row in data.rows("SELECT player_id FROM players ORDER BY 1")]
    finally:
        data.close()


def test_a_replay_without_publish_reports_and_leaves_the_catalog(tmp_path):
    bucket, _ = bucket_with_captures(tmp_path)
    catalog = bucket.get_json("state/manifests.json")

    result = replay.replay_canonical(bucket)

    assert result["status"] == "checked"
    assert result["requests_replayed"] == 2
    assert result["rows"]["players"] == 1
    assert result["current_rows"]["players"] == 1
    assert bucket.get_json("state/manifests.json") == catalog


def test_a_published_replay_replaces_the_read_catalog_and_keeps_a_later_batch(tmp_path):
    bucket, _ = bucket_with_captures(tmp_path)
    late = publish(
        tmp_path / "remote",
        {
            "provider": "test",
            "retrieved_at": "2026-09-10T00:00:00+00:00",
            "evidence_basis": "captured",
            "source_sha256": "e" * 64,
        },
        {"teams": [{"team_id": "late", "name": "Late"}]},
    )

    def collection_during_replay(key):
        current = bucket.get_json(key)
        bucket.put_json(key, manifest_state([*current["manifests"], late]))

    bucket.before_conditional_write = collection_during_replay
    result = replay.replay_canonical(bucket, publish=True)

    batches = [batch["batch_id"] for batch in bucket.get_json("state/manifests.json")["manifests"]]
    assert sorted(batches) == sorted([result["batch_id"], late["batch_id"]])
    assert "old-normalization" not in player_ids(bucket)
    assert len(player_ids(bucket)) == 1


def test_a_corrupted_raw_capture_stops_the_replay_before_any_write(tmp_path):
    bucket, squad = bucket_with_captures(tmp_path)
    catalog = bucket.get_json("state/manifests.json")
    (bucket.directory / squad["raw_path"]).write_bytes(b"corrupt")

    with pytest.raises(ValueError, match="hash mismatch"):
        replay.replay_canonical(bucket, publish=True)

    assert bucket.get_json("state/manifests.json") == catalog


def test_ingestion_during_a_replay_cannot_read_the_r2_catalog(tmp_path, monkeypatch):
    bucket, _ = bucket_with_captures(tmp_path)
    monkeypatch.setenv("R2_ACCOUNT_ID", "account")
    monkeypatch.setenv("R2_DATA_BUCKET", "bucket")
    seen = []
    normalize = replay.api.normalize

    def recording_normalize(record, body, workspace):
        seen.append(os.environ.get("R2_DATA_BUCKET"))
        return normalize(record, body, workspace)

    monkeypatch.setattr(replay.api, "normalize", recording_normalize)
    replay.replay_canonical(bucket)

    assert seen == [None]
    assert os.environ["R2_DATA_BUCKET"] == "bucket"
