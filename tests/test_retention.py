from datetime import UTC, datetime

import pytest

from epl_forecast.retention import build_retention_plan, retention_status, validate_retention_plan


class Store:
    def __init__(self):
        self.objects = {
            "state/canonical-snapshot.json": {
                "database_key": "snapshots/current.duckdb",
                "manifest_key": "snapshots/current.manifest.json",
            },
            "state/fits/eng-premier-league.json": {
                "database_key": "fits/eng-premier-league/current.duckdb"
            },
            "state/results/eng-premier-league.json": {
                "database_key": "results/eng-premier-league/current.duckdb"
            },
            "state/manifests.json": {
                "manifests": [
                    {
                        "batch_id": "selected",
                        "files": [{"path": "parquet/fixtures/selected.parquet"}],
                    }
                ]
            },
        }
        self.rows = {
            "parquet/": ["parquet/fixtures/selected.parquet", "parquet/fixtures/old.parquet"],
            "manifests/": ["manifests/selected.json", "manifests/old.json"],
            "snapshots/": [
                "snapshots/current.duckdb",
                "snapshots/current.manifest.json",
                "snapshots/old.duckdb",
            ],
            "fits/": [
                "fits/eng-premier-league/current.duckdb",
                "fits/eng-premier-league/old.duckdb",
            ],
            "results/": [
                "results/eng-premier-league/current.duckdb",
                "results/eng-premier-league/old.duckdb",
            ],
            "runs/forecasts/": ["runs/forecasts/old/forecast.json"],
            "runs/snapshots/": ["runs/snapshots/old/data.parquet"],
            "research/": ["research/keep-until-reviewed.json"],
        }

    def get_json(self, key, default=None):
        return self.objects.get(key, default)

    def inventory(self, prefix=""):
        for key in self.rows.get(prefix, []):
            yield {
                "key": key,
                "bytes": len(key),
                "etag": key,
                "last_modified": "2026-09-18T00:00:00+00:00",
            }


def test_retention_plan_protects_live_targets_and_only_lists_candidates():
    plan = build_retention_plan(Store())
    candidates = {row["key"] for row in plan["delete_candidates"]}
    assert candidates == {
        "parquet/fixtures/old.parquet",
        "manifests/old.json",
        "snapshots/old.duckdb",
        "fits/eng-premier-league/old.duckdb",
        "results/eng-premier-league/old.duckdb",
        "runs/forecasts/old/forecast.json",
        "runs/snapshots/old/data.parquet",
    }
    assert "snapshots/current.duckdb" in plan["protected_objects"]
    assert "manifests/selected.json" in plan["protected_objects"]
    assert [row["key"] for row in plan["review_required"]] == ["research/keep-until-reviewed.json"]
    assert plan["mode"] == "read_only"


def test_retention_plan_must_match_a_fresh_inventory_exactly():
    plan = build_retention_plan(Store())
    validate_retention_plan(plan, build_retention_plan(Store()))
    changed = {**plan, "delete_candidates": plan["delete_candidates"][:-1]}
    with pytest.raises(ValueError, match="delete_candidates changed"):
        validate_retention_plan(changed, plan)


def test_retention_status_separates_billable_and_product_occupancy():
    plan = build_retention_plan(Store())
    data = [
        {"key": "research/archive", "bytes": 700},
        {"key": "results/current", "bytes": 200},
    ]
    publish = [{"key": "forecasts/current", "bytes": 100}]
    policy = {
        "baseline": {
            "recorded_at": "2026-09-01T00:00:00+00:00",
            "data_objects": 2,
            "data_bytes": 900,
            "publish_objects": 1,
            "publish_bytes": 100,
            "research_objects": 1,
            "research_bytes": 700,
        },
        "review": {
            "candidate_objects": 100,
            "candidate_bytes": 10_000,
            "superseded_generations": 100,
            "total_object_growth": 100,
            "product_bytes": 10_000,
            "research_growth_bytes": 0,
            "days_since_review": 90,
        },
    }
    status = retention_status(
        plan,
        data,
        publish,
        policy,
        now=datetime(2026, 9, 18, tzinfo=UTC),
    )
    assert status["measures"]["billable_bytes"] == 1000
    assert status["measures"]["product_bytes"] == 300
    assert status["measures"]["research_byte_growth"] == 0
    assert status["cleanup_review_required"] is False

    data[0]["bytes"] += 1
    alert = retention_status(
        plan,
        data,
        publish,
        policy,
        now=datetime(2026, 9, 18, tzinfo=UTC),
    )
    assert alert["cleanup_review_required"] is True
    assert "research_byte_growth" in alert["review_reasons"][0]
