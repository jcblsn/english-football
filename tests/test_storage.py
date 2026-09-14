import json
import os

import pytest

from epl_forecast.datasets import Dataset, publish
from epl_forecast.storage import R2Config, load_environment


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
    local = tmp_path / "local"
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

    data = Dataset(local, store=Store())
    try:
        assert data.rows("SELECT team_id, name FROM teams") == [
            {"team_id": "arsenal", "name": "Arsenal"}
        ]
        assert json.loads(json.dumps(data.provenance()))["batches"] == [manifest["batch_id"]]
    finally:
        data.close()
