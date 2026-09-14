"""Immutable HTTP captures and resumable local request checkpoints."""

import fcntl
import json
import os
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from epl_forecast.storage import file_hash, json_bytes, sha256_bytes, write_immutable


class SourceAccessError(RuntimeError):
    pass


class QuotaReached(SourceAccessError):
    pass


class WriterBusy(SourceAccessError):
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


@contextmanager
def writer_lock(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with (root / "writer.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise WriterBusy("Another local data writer is running") from None
        yield


def retain(root, provider, url, payload, retrieved_at, evidence_basis, context=None):
    root = Path(root)
    digest = sha256_bytes(payload)
    extension = "csv" if provider == "football_data" else "json"
    path = root / "raw" / provider / f"{digest}.{extension}"
    write_immutable(path, payload)
    record = {
        "provider": provider,
        "url": url,
        "retrieved_at": retrieved_at,
        "evidence_basis": evidence_basis,
        "source_sha256": digest,
        "raw_path": str(path.relative_to(root)),
        "context": context or {},
    }
    request_id = sha256_bytes(json_bytes(record))
    write_immutable(root / "requests" / f"{request_id}.json", json_bytes(record))
    return record


class Fetcher:
    def __init__(self, root=Path("data"), reserve=0, store=None):
        self.root, self.reserve, self.store = Path(root), reserve, store
        self.last_call = 0.0
        self.interval = 0.26
        self.remaining = None
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

    def get(self, provider, url, *, context=None, max_age=None, historical=False):
        old = self.latest.get(url)
        if old:
            age = (datetime.now(UTC) - datetime.fromisoformat(old["retrieved_at"])).total_seconds()
            if historical or (max_age is not None and age < max_age):
                path = self.root / old["raw_path"]
                if not path.exists() and self.store:
                    self.store.download(old["raw_path"], path)
                if file_hash(path) != old["source_sha256"]:
                    raise ValueError(f"Raw checksum mismatch: {path}")
                return old, path.read_bytes()
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
                if self.remaining is not None and self.remaining <= self.reserve:
                    raise QuotaReached("Daily backfill budget exhausted; resume after midnight UTC")
                time.sleep(max(0, self.interval - (time.monotonic() - self.last_call)))
                self.last_call = time.monotonic()
            try:
                with urlopen(Request(url, headers=headers), timeout=45) as response:
                    payload = response.read()
                    limits = {k.lower(): v for k, v in response.headers.items()}
                    if api:
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
        return record, payload
