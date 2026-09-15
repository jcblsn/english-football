import io
import json
from hashlib import sha256
from urllib.error import HTTPError

import pytest

from epl_forecast.data import capture


class Response(io.BytesIO):
    headers = {"x-ratelimit-requests-remaining": "7000", "x-ratelimit-limit": "300"}


def test_http_200_api_errors_are_not_successful_checkpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("API_FOOTBALL_KEY", "test-only-credential")
    monkeypatch.setattr(
        capture,
        "urlopen",
        lambda *args, **kwargs: Response(b'{"errors":{"token":"invalid"},"response":[]}'),
    )
    with pytest.raises(capture.SourceAccessError, match="invalid"):
        capture.Fetcher(tmp_path).get("api_football", "https://example.test/players")
    assert not list((tmp_path / "requests").glob("*.json"))


def test_transient_retry_then_offline_checkpoint_reuse(tmp_path, monkeypatch):
    monkeypatch.setenv("API_FOOTBALL_KEY", "test-only-credential")
    monkeypatch.setattr(capture.time, "sleep", lambda seconds: None)
    calls = []

    def fetch(request, **kwargs):
        calls.append(request)
        if len(calls) == 1:
            raise HTTPError(request.full_url, 503, "unavailable", {}, None)
        return Response(b'{"errors":{},"response":[]}')

    monkeypatch.setattr(capture, "urlopen", fetch)
    fetcher = capture.Fetcher(tmp_path)
    first = fetcher.get("api_football", "https://example.test/players", historical=True)
    assert len(calls) == 2 and len(fetcher.records) == 1
    monkeypatch.delenv("API_FOOTBALL_KEY")
    assert (
        capture.Fetcher(tmp_path).get(
            "api_football", "https://example.test/players", historical=True
        )
        == first
    )
    assert len(calls) == 2
    assert all(
        "test-only-credential" not in p.read_text() for p in (tmp_path / "requests").glob("*.json")
    )


def test_fetcher_counts_api_football_attempts_and_last_daily_quota(tmp_path, monkeypatch):
    monkeypatch.setenv("API_FOOTBALL_KEY", "test-only-credential")
    monkeypatch.setattr(capture.time, "sleep", lambda seconds: None)
    calls = []

    class Quota(io.BytesIO):
        headers = {"X-RateLimit-Requests-Limit": "7500", "X-RateLimit-Requests-Remaining": "7412"}

    def fetch(request, **kwargs):
        calls.append(request)
        if len(calls) == 1:
            raise HTTPError(request.full_url, 503, "unavailable", {}, None)
        return Quota(b'{"errors":{},"response":[]}')

    monkeypatch.setattr(capture, "urlopen", fetch)
    fetcher = capture.Fetcher(tmp_path)
    assert fetcher.usage() == {
        "calls": 0,
        "daily_limit": None,
        "daily_remaining": None,
        "observed_at": None,
    }
    fetcher.get("api_football", "https://example.test/players", max_age=3600)
    fetcher.get("api_football", "https://example.test/players", max_age=3600)
    fetcher.get("fpl", "https://example.test/fpl")
    usage = fetcher.usage()
    assert len(calls) == 3
    assert usage["calls"] == 2
    assert (usage["daily_limit"], usage["daily_remaining"]) == (7500, 7412)
    assert usage["observed_at"] is not None


def test_fetcher_keeps_unknown_quota_when_headers_are_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("API_FOOTBALL_KEY", "test-only-credential")

    class Bare(io.BytesIO):
        headers = {}

    monkeypatch.setattr(
        capture, "urlopen", lambda *args, **kwargs: Bare(b'{"errors":[],"response":[]}')
    )
    fetcher = capture.Fetcher(tmp_path)
    fetcher.get("api_football", "https://example.test/players")
    assert fetcher.usage() == {
        "calls": 1,
        "daily_limit": None,
        "daily_remaining": None,
        "observed_at": None,
    }


def test_quota_reserve_and_writer_lock_prevent_new_requests(tmp_path, monkeypatch):
    monkeypatch.setenv("API_FOOTBALL_KEY", "test-only-credential")

    def forbidden(*args, **kwargs):
        raise AssertionError("No network request should be attempted")

    monkeypatch.setattr(capture, "urlopen", forbidden)
    fetcher = capture.Fetcher(tmp_path, reserve=1000)
    fetcher.remaining = 1000
    with pytest.raises(capture.QuotaReached):
        fetcher.get("api_football", "https://example.test/players")
    with capture.writer_lock(tmp_path):
        with pytest.raises(capture.SourceAccessError, match="writer"):
            with capture.writer_lock(tmp_path):
                pass


def test_fetcher_reads_a_due_checkpoint_payload_from_remote_storage(tmp_path):
    payload = b'{"response":[]}'
    digest = sha256(payload).hexdigest()
    record = {
        "provider": "api_football",
        "url": "https://example.test/players",
        "retrieved_at": "2026-09-14T12:00:00+00:00",
        "evidence_basis": "captured",
        "source_sha256": digest,
        "raw_path": f"raw/api_football/{digest}.json",
        "context": {},
    }

    class Store:
        def get_json(self, key, default=None):
            return {"latest_by_url": {record["url"]: record}}

        def download(self, key, destination):
            assert key == record["raw_path"]
            destination.parent.mkdir(parents=True)
            destination.write_bytes(payload)

    fetcher = capture.Fetcher(tmp_path, store=Store())
    returned_record, returned_payload = fetcher.get("api_football", record["url"], historical=True)
    assert returned_record == record
    assert returned_payload == payload
    assert json.loads((tmp_path / record["raw_path"]).read_text()) == {"response": []}
