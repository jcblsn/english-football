import hashlib
import json
import os
from collections import Counter
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

import boto3
from botocore.exceptions import ClientError


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json_bytes(value))


def write_immutable(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(payload)
    except FileExistsError:
        if path.read_bytes() != payload:
            raise ValueError(f"Refusing to overwrite immutable file: {path}") from None


def load_environment(path: Path = Path(".env")) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        name, separator, value = line.partition("=")
        name = name.strip()
        if separator and name and name not in os.environ:
            os.environ[name] = value.strip().strip("\"'")


class ConditionalWriteFailed(RuntimeError):
    """Another writer changed the object after this writer read it."""


@dataclass(frozen=True)
class R2Config:
    account_id: str
    bucket: str
    access_key_id: str
    secret_access_key: str

    @classmethod
    def from_environment(cls, bucket_variable: str) -> "R2Config":
        names = (
            "R2_ACCOUNT_ID",
            bucket_variable,
            "R2_ACCESS_KEY_ID",
            "R2_SECRET_ACCESS_KEY",
        )
        missing = [name for name in names if not os.environ.get(name)]
        if missing:
            raise ValueError(f"Missing R2 settings: {', '.join(missing)}")
        return cls(*(os.environ[name] for name in names))

    @property
    def endpoint(self) -> str:
        return f"{self.account_id}.r2.cloudflarestorage.com"


class R2Store:
    def __init__(self, config: R2Config, client=None):
        self.config = config
        self._metrics = Counter()
        self._metrics_lock = Lock()
        self.client = client or boto3.client(
            "s3",
            endpoint_url=f"https://{config.endpoint}",
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            region_name="auto",
        )

    def _record(self, operation: str, *, read=0, written=0) -> None:
        with self._metrics_lock:
            self._metrics[f"{operation.lower()}_requests"] += 1
            self._metrics["response_bytes"] += read
            self._metrics["request_bytes"] += written

    def metrics(self) -> dict[str, int]:
        with self._metrics_lock:
            return dict(sorted(self._metrics.items()))

    @classmethod
    def from_environment(cls, bucket_variable: str) -> "R2Store":
        return cls(R2Config.from_environment(bucket_variable))

    def uri(self, key: str) -> str:
        return f"s3://{self.config.bucket}/{key.lstrip('/')}"

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.config.bucket, Key=key)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in {"404", "NoSuchKey"}:
                return False
            raise
        finally:
            self._record("HEAD")
        return True

    def get_bytes(self, key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.config.bucket, Key=key)
        except ClientError as error:
            self._record("GET")
            if error.response.get("Error", {}).get("Code") in {"404", "NoSuchKey"}:
                raise FileNotFoundError(key) from None
            raise
        payload = response["Body"].read()
        self._record("GET", read=len(payload))
        return payload

    def get_json(self, key: str, default=None):
        try:
            return json.loads(self.get_bytes(key))
        except FileNotFoundError:
            return default

    def identities(self, keys) -> dict[str, str | None]:
        """A compact change token for each key, or None where the object is absent.

        The token is the `sha256` metadata that `put_bytes` writes, and the ETag when an
        object has no such metadata. One HEAD request answers for each key, so a reader that
        only needs to know whether a mutable pointer changed never reads its body.
        """
        keys = list(keys)
        if not keys:
            return {}
        with ThreadPoolExecutor(max_workers=min(16, len(keys))) as pool:
            return dict(zip(keys, pool.map(self._identity, keys), strict=True))

    def _identity(self, key: str) -> str | None:
        try:
            head = self.client.head_object(Bucket=self.config.bucket, Key=key)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        finally:
            self._record("HEAD")
        return (
            head.get("Metadata", {}).get("sha256")
            or head.get("ETag")
            or sha256_bytes(self.get_bytes(key))
        )

    def get_json_versioned(self, key: str, default=None) -> tuple[Any, str | None]:
        """The JSON value and its ETag, or the default and None when the object is absent."""
        try:
            response = self.client.get_object(Bucket=self.config.bucket, Key=key)
        except ClientError as error:
            self._record("GET")
            if error.response.get("Error", {}).get("Code") in {"404", "NoSuchKey"}:
                return default, None
            raise
        payload = response["Body"].read()
        self._record("GET", read=len(payload))
        return json.loads(payload), response["ETag"]

    def put_json_if(self, key: str, value, version: str | None) -> None:
        """Write only when the object still has this ETag, or is still absent when it is None."""
        payload = json_bytes(value)
        condition = {"IfMatch": version} if version is not None else {"IfNoneMatch": "*"}
        try:
            self.client.put_object(
                Bucket=self.config.bucket,
                Key=key,
                Body=payload,
                Metadata={"sha256": sha256_bytes(payload)},
                ContentType="application/json",
                **condition,
            )
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code")
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code in {"PreconditionFailed", "ConditionalRequestConflict"} or status in {409, 412}:
                raise ConditionalWriteFailed(key) from None
            raise
        finally:
            self._record("PUT", written=len(payload))

    def put_bytes(
        self,
        key: str,
        payload: bytes,
        *,
        immutable: bool = False,
        content_type: str | None = None,
    ) -> None:
        digest = sha256_bytes(payload)
        arguments = {
            "Bucket": self.config.bucket,
            "Key": key,
            "Body": payload,
            "Metadata": {"sha256": digest},
        }
        if content_type:
            arguments["ContentType"] = content_type
        self._put_object(arguments, digest, len(payload), immutable)

    def _put_object(self, arguments: dict, digest: str, size: int, immutable: bool) -> None:
        if immutable:
            arguments["IfNoneMatch"] = "*"
        try:
            self.client.put_object(**arguments)
        except Exception as error:
            if immutable:
                try:
                    existing_digest = self._remote_digest(arguments["Key"])
                except Exception:
                    raise error from None
                if existing_digest == digest:
                    return
                if isinstance(error, ClientError):
                    code = error.response.get("Error", {}).get("Code")
                    status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                    if code in {"PreconditionFailed", "ConditionalRequestConflict"} or status in {
                        409,
                        412,
                    }:
                        raise ValueError(
                            f"Refusing to overwrite immutable R2 object: {arguments['Key']}"
                        ) from None
            raise
        finally:
            self._record("PUT", written=size)

    def _remote_digest(self, key: str) -> str | None:
        try:
            head = self.client.head_object(Bucket=self.config.bucket, Key=key)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        finally:
            self._record("HEAD")
        stored = head.get("Metadata", {}).get("sha256")
        if stored:
            return stored
        response = self.client.get_object(Bucket=self.config.bucket, Key=key)
        digest = hashlib.sha256()
        read = 0
        while chunk := response["Body"].read(1024 * 1024):
            digest.update(chunk)
            read += len(chunk)
        self._record("GET", read=read)
        return digest.hexdigest()

    def put_json(self, key: str, value, *, immutable: bool = False) -> None:
        self.put_bytes(key, json_bytes(value), immutable=immutable, content_type="application/json")

    def download(self, key: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            response = self.client.get_object(Bucket=self.config.bucket, Key=key)
        except ClientError as error:
            self._record("GET")
            if error.response.get("Error", {}).get("Code") in {"404", "NoSuchKey"}:
                raise FileNotFoundError(key) from None
            raise
        read = 0
        with destination.open("wb") as stream:
            while chunk := response["Body"].read(1024 * 1024):
                stream.write(chunk)
                read += len(chunk)
        self._record("GET", read=read)

    def upload(self, source: Path, key: str, *, immutable: bool = False) -> None:
        content_types = {
            ".csv": "text/csv",
            ".json": "application/json",
            ".parquet": "application/vnd.apache.parquet",
        }
        digest = file_hash(source)
        arguments = {
            "Bucket": self.config.bucket,
            "Key": key,
            "Metadata": {"sha256": digest},
        }
        content_type = content_types.get(source.suffix.lower())
        if content_type:
            arguments["ContentType"] = content_type
        with source.open("rb") as stream:
            arguments["Body"] = stream
            self._put_object(arguments, digest, source.stat().st_size, immutable)

    def keys(self, prefix: str = "") -> Iterator[str]:
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.config.bucket, Prefix=prefix):
            self._record("LIST")
            for row in page.get("Contents", []):
                yield row["Key"]

    def inventory(self, prefix: str = "") -> Iterator[dict]:
        """List exact object keys and sizes without reading object bodies."""
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.config.bucket, Prefix=prefix):
            self._record("LIST")
            for row in page.get("Contents", []):
                yield {
                    "key": row["Key"],
                    "bytes": row["Size"],
                    "etag": row.get("ETag", "").strip('"'),
                    "last_modified": row["LastModified"].isoformat(),
                }

    def delete_keys(self, keys, batch_size: int = 1000) -> int:
        """Delete exact object keys in bounded S3 batches."""
        keys = list(keys)
        deleted = 0
        for offset in range(0, len(keys), batch_size):
            batch = keys[offset : offset + batch_size]
            try:
                response = self.client.delete_objects(
                    Bucket=self.config.bucket,
                    Delete={"Objects": [{"Key": key} for key in batch], "Quiet": False},
                )
            finally:
                self._record("DELETE")
            errors = response.get("Errors", [])
            if errors:
                detail = ", ".join(f"{row.get('Key')}: {row.get('Code')}" for row in errors[:5])
                raise RuntimeError(f"R2 deletion failed: {detail}")
            deleted += len(batch)
        return deleted

    def configure_duckdb(self, connection, name: str = "page324_r2") -> None:
        def quote(value: str) -> str:
            return "'" + value.replace("'", "''") + "'"

        connection.execute("INSTALL httpfs")
        connection.execute("LOAD httpfs")
        connection.execute(
            f"CREATE OR REPLACE SECRET {name} ("
            "TYPE s3, "
            f"KEY_ID {quote(self.config.access_key_id)}, "
            f"SECRET {quote(self.config.secret_access_key)}, "
            "REGION 'auto', "
            f"ENDPOINT {quote(self.config.endpoint)}, "
            "URL_STYLE 'path', USE_SSL true, "
            f"SCOPE {quote(f's3://{self.config.bucket}')})"
        )


def r2_store_if_configured(bucket_variable: str) -> R2Store | None:
    names = (
        "R2_ACCOUNT_ID",
        bucket_variable,
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
    )
    return (
        R2Store.from_environment(bucket_variable) if all(os.environ.get(n) for n in names) else None
    )
