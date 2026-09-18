"""Immutable HTTP captures and resumable local request checkpoints."""

import gzip
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from epl_forecast.storage import json_bytes, sha256_bytes, write_immutable


class SourceAccessError(RuntimeError):
    pass


class QuotaReached(SourceAccessError):
    pass


def api_key():
    value = os.environ.get("API_FOOTBALL_KEY")
    if not value and Path(".env").exists():
        for line in Path(".env").read_text().splitlines():
            if line.startswith("API_FOOTBALL_KEY="):
                value = line.partition("=")[2].strip().strip("\"'")
    if not value:
        raise SourceAccessError("Set API_FOOTBALL_KEY in the environment or ignored .env")
    return value


def decode_capture(record: dict, stored: bytes) -> bytes:
    try:
        payload = gzip.decompress(stored) if record.get("storage_encoding") == "gzip" else stored
    except (gzip.BadGzipFile, EOFError, OSError):
        raise ValueError(f"Raw checksum mismatch: {record['raw_path']}") from None
    if sha256_bytes(payload) != record["source_sha256"]:
        raise ValueError(f"Raw checksum mismatch: {record['raw_path']}")
    return payload


def retain(root, provider, url, payload, retrieved_at, evidence_basis, context=None):
    root = Path(root)
    digest = sha256_bytes(payload)
    extension = "csv" if provider == "football_data" else "json"
    path = root / "raw" / provider / f"{digest}.{extension}.gz"
    write_immutable(path, gzip.compress(payload, compresslevel=6, mtime=0))
    record = {
        "provider": provider,
        "url": url,
        "retrieved_at": retrieved_at,
        "evidence_basis": evidence_basis,
        "source_sha256": digest,
        "raw_path": str(path.relative_to(root)),
        "storage_encoding": "gzip",
        "context": context or {},
    }
    request_id = sha256_bytes(json_bytes(record))
    write_immutable(root / "requests" / f"{request_id}.json", json_bytes(record))
    return record


class Fetcher:
    def __init__(self, root, store=None):
        self.root, self.store = Path(root), store
        self.last_call = 0.0
        self.interval = 0.26
        self.remaining = None
        self.api_calls = 0
        self.api_limit = self.api_remaining = self.api_observed_at = None
        local = [json.loads(p.read_text()) for p in (self.root / "requests").glob("*.json")]
        remote = (
            list(store.get_json("state/collection.json", {}).get("latest_by_url", {}).values())
            if store
            else []
        )
        self.records = list(
            {
                (record["url"], record["retrieved_at"], record["source_sha256"]): record
                for record in [*remote, *local]
            }.values()
        )
        self.latest = {}
        for r in sorted(self.records, key=lambda r: r["retrieved_at"]):
            self.latest[r["url"]] = r
        self.captured = set()

    def reusable(self, url, max_age=None, historical=False):
        """True when a retained response for this URL can stand in for a new request."""
        old = self.latest.get(url)
        if not old:
            return False
        age = (datetime.now(UTC) - datetime.fromisoformat(old["retrieved_at"])).total_seconds()
        return historical or (max_age is not None and age < max_age)

    def usage(self):
        """API-Football requests sent by this fetcher and the last daily quota headers."""
        return {
            "calls": self.api_calls,
            "daily_limit": self.api_limit,
            "daily_remaining": self.api_remaining,
            "observed_at": self.api_observed_at,
        }

    def observe(self, headers):
        values = {k.lower(): v for k, v in (headers or {}).items()}
        quota = {}
        for name in ("limit", "remaining"):
            try:
                quota[name] = int(values[f"x-ratelimit-requests-{name}"])
            except (KeyError, TypeError, ValueError):
                quota[name] = None
        if quota["limit"] is not None or quota["remaining"] is not None:
            self.api_limit, self.api_remaining = quota["limit"], quota["remaining"]
            self.api_observed_at = datetime.now(UTC).isoformat()

    def is_new(self, record):
        """True only for a response that this fetcher retrieved, not for retained evidence."""
        return (record["url"], record["retrieved_at"]) in self.captured

    def get(self, provider, url, *, context=None, max_age=None, historical=False):
        if self.reusable(url, max_age, historical):
            old = self.latest[url]
            path = self.root / old["raw_path"]
            if not path.exists() and self.store:
                self.store.download(old["raw_path"], path)
            return old, decode_capture(old, path.read_bytes())
        api = provider == "api_football"
        headers = {"User-Agent": "epl-forecast/0.1 (local research)"}
        if api:
            headers["x-apisports-key"] = api_key()
        if provider == "understat":
            headers.update(
                {"X-Requested-With": "XMLHttpRequest", "Referer": "https://understat.com/"}
            )
        for attempt in range(4):
            if api:
                if self.remaining is not None and self.remaining <= 0:
                    raise QuotaReached("The API-Football daily quota is exhausted")
                time.sleep(max(0, self.interval - (time.monotonic() - self.last_call)))
                self.last_call = time.monotonic()
                self.api_calls += 1
            try:
                with urlopen(Request(url, headers=headers), timeout=45) as response:
                    payload = response.read()
                    limits = {k.lower(): v for k, v in response.headers.items()}
                    if api:
                        self.observe(limits)
                        self.remaining = int(
                            limits.get("x-ratelimit-requests-remaining", self.remaining or 7500)
                        )
                        minute = int(limits.get("x-ratelimit-limit", 300))
                        self.interval = max(0.26, 60 / minute + 0.01)
                        if int(limits.get("x-ratelimit-remaining", 1)) == 0:
                            time.sleep(60)
                if api:
                    body = json.loads(payload)
                    errors = body.get("errors")
                    if errors:
                        message = json.dumps(errors)
                        if any(
                            k in str(errors).lower()
                            for k in ("ratelimit", "rate limit", "requests limit")
                        ):
                            if attempt < 3:
                                time.sleep(60)
                                continue
                        raise SourceAccessError(f"API-Football {url}: {message}")
                break
            except HTTPError as error:
                if api:
                    self.observe(error.headers)
                if error.code not in (429, 499, 500, 502, 503, 504) or attempt == 3:
                    raise SourceAccessError(f"HTTP {error.code}: {url}") from None
                delay = min(60, max(2**attempt, float(error.headers.get("Retry-After", 0))))
                time.sleep(delay)
            except (URLError, TimeoutError) as error:
                if attempt == 3:
                    raise SourceAccessError(
                        f"Cannot retrieve {url}: {type(error).__name__}"
                    ) from None
                time.sleep(2**attempt)
        else:
            raise SourceAccessError(f"Retries exhausted: {url}")
        record = retain(
            self.root,
            provider,
            url,
            payload,
            datetime.now(UTC).isoformat(),
            "retrospective" if historical else "captured",
            context,
        )
        self.latest[url] = record
        self.records.append(record)
        self.captured.add((url, record["retrieved_at"]))
        return record, payload
