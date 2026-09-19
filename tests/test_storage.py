import json
import os
from datetime import UTC, datetime

import pytest
from botocore.exceptions import ClientError

from epl_forecast.datasets import Dataset, publish
from epl_forecast.storage import ConditionalWriteFailed, R2Config, R2Store, load_environment


def test_environment_file_only_fills_missing_values(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("export FIRST='one'\nSECOND=two\n# THIRD=three\n")
    monkeypatch.setenv("FIRST", "kept")
    monkeypatch.delenv("SECOND", raising=False)
    load_environment(env)
    assert os.environ["FIRST"] == "kept"
    assert os.environ["SECOND"] == "two"


def test_r2_configuration_names_every_missing_setting(monkeypatch):
    for name in (
        "R2_ACCOUNT_ID",
        "R2_DATA_BUCKET",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="R2_ACCOUNT_ID.*R2_DATA_BUCKET"):
        R2Config.from_environment("R2_DATA_BUCKET")


def test_dataset_reads_manifest_catalog_and_parquet_from_a_store(tmp_path):
    remote = tmp_path / "remote"
    request = {
        "provider": "test",
        "retrieved_at": "2026-09-14T12:00:00+00:00",
        "evidence_basis": "captured",
        "source_sha256": "a" * 64,
    }
    manifest = publish(
        remote,
        request,
        {
            "teams": [
                {"team_id": "arsenal", "name": "Arsenal", "api_id": 1},
            ]
        },
    )

    class Store:
        def get_json(self, key, default=None):
            assert key == "state/manifests.json"
            return {"manifests": [manifest]}

        def uri(self, key):
            return str(remote / key)

        def configure_duckdb(self, connection):
            pass

    data = Dataset(store=Store())
    try:
        assert data.rows("SELECT team_id, name FROM teams") == [
            {"team_id": "arsenal", "name": "Arsenal"}
        ]
        assert json.loads(json.dumps(data.provenance()))["batches"] == [manifest["batch_id"]]
    finally:
        data.close()


class CatalogStore:
    def __init__(self, directory, manifests):
        self.directory = directory
        self.manifests = manifests

    def get_json(self, key, default=None):
        return {"manifests": self.manifests} if key == "state/manifests.json" else default

    def uri(self, key):
        return str(self.directory / key)

    def configure_duckdb(self, connection):
        pass


def team_request(source):
    return {
        "provider": "test",
        "retrieved_at": "2026-09-14T12:00:00+00:00",
        "evidence_basis": "captured",
        "source_sha256": source * 64,
    }


def test_a_workspace_adds_only_batches_that_are_not_in_r2(tmp_path):
    remote = tmp_path / "remote"
    workspace = tmp_path / "workspace"
    tables = {"teams": [{"team_id": "arsenal", "name": "Arsenal", "api_id": 1}]}
    manifest = publish(remote, team_request("a"), tables)
    stale = publish(workspace, team_request("a"), tables)
    assert stale["batch_id"] == manifest["batch_id"]
    for file in stale["files"]:
        (workspace / file["path"]).unlink()
    publish(workspace, team_request("b"), {"teams": [{"team_id": "chelsea", "name": "Chelsea"}]})

    data = Dataset(store=CatalogStore(remote, [manifest]), workspace=workspace)
    try:
        assert data.rows("SELECT team_id FROM teams ORDER BY 1") == [
            {"team_id": "arsenal"},
            {"team_id": "chelsea"},
        ]
    finally:
        data.close()


def test_a_dataset_needs_r2_or_a_capture_workspace(monkeypatch):
    for name in ("R2_ACCOUNT_ID", "R2_DATA_BUCKET", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="R2 data bucket or a capture workspace"):
        Dataset()


def test_a_conditional_r2_write_sends_its_condition_and_reports_a_conflict():
    calls = []

    class Client:
        def put_object(self, **arguments):
            calls.append(arguments)
            if arguments.get("IfMatch") == "stale":
                raise ClientError(
                    {
                        "Error": {"Code": "PreconditionFailed"},
                        "ResponseMetadata": {"HTTPStatusCode": 412},
                    },
                    "PutObject",
                )

    store = R2Store(R2Config("account", "bucket", "key", "secret"), client=Client())
    store.put_json_if("state/manifests.json", {"manifests": []}, None)
    store.put_json_if("state/manifests.json", {"manifests": []}, "current")
    with pytest.raises(ConditionalWriteFailed):
        store.put_json_if("state/manifests.json", {"manifests": []}, "stale")
    assert calls[0]["IfNoneMatch"] == "*" and "IfMatch" not in calls[0]
    assert calls[1]["IfMatch"] == "current" and "IfNoneMatch" not in calls[1]


def test_object_identities_use_one_head_request_and_report_absence():
    calls = []

    class Client:
        def head_object(self, Bucket, Key):
            calls.append(Key)
            if Key == "missing.json":
                raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
            if Key == "legacy.json":
                return {"ETag": '"abc"'}
            return {"Metadata": {"sha256": "d" * 64}, "ETag": '"ignored"'}

        def get_object(self, Bucket, Key):
            raise AssertionError(f"An identity check must not read a body: {Key}")

    store = R2Store(R2Config("account", "bucket", "key", "secret"), client=Client())
    assert store.identities(("record.json", "legacy.json", "missing.json")) == {
        "record.json": "d" * 64,
        "legacy.json": '"abc"',
        "missing.json": None,
    }
    assert sorted(calls) == ["legacy.json", "missing.json", "record.json"]
    assert store.identities(()) == {}


def test_inventory_returns_exact_list_metadata_and_counts_the_request():
    class Paginator:
        def paginate(self, **arguments):
            assert arguments == {"Bucket": "bucket", "Prefix": "results/"}
            return [
                {
                    "Contents": [
                        {
                            "Key": "results/current.duckdb",
                            "Size": 123,
                            "ETag": '"etag"',
                            "LastModified": datetime(2026, 9, 18, tzinfo=UTC),
                        }
                    ]
                }
            ]

    class Client:
        def get_paginator(self, operation):
            assert operation == "list_objects_v2"
            return Paginator()

    store = R2Store(R2Config("account", "bucket", "key", "secret"), client=Client())
    assert list(store.inventory("results/")) == [
        {
            "key": "results/current.duckdb",
            "bytes": 123,
            "etag": "etag",
            "last_modified": "2026-09-18T00:00:00+00:00",
        }
    ]
    assert store.metrics() == {"list_requests": 1, "request_bytes": 0, "response_bytes": 0}


def test_exact_key_deletion_uses_bounded_batches_and_reports_errors():
    calls = []

    class Client:
        def delete_objects(self, **arguments):
            calls.append(arguments)
            return {"Deleted": arguments["Delete"]["Objects"]}

    store = R2Store(R2Config("account", "bucket", "key", "secret"), client=Client())
    keys = [f"old/{index}" for index in range(5)]
    assert store.delete_keys(keys, batch_size=2) == 5
    assert [[row["Key"] for row in call["Delete"]["Objects"]] for call in calls] == [
        ["old/0", "old/1"],
        ["old/2", "old/3"],
        ["old/4"],
    ]
    assert store.metrics()["delete_requests"] == 3

    class FailingClient:
        def delete_objects(self, **arguments):
            return {"Errors": [{"Key": "old/0", "Code": "AccessDenied"}]}

    failing = R2Store(R2Config("account", "bucket", "key", "secret"), client=FailingClient())
    with pytest.raises(RuntimeError, match="old/0: AccessDenied"):
        failing.delete_keys(["old/0"])
