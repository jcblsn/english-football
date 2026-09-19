from datetime import UTC, datetime

import pytest

from epl_forecast.competitions import COMPETITION_IDS
from epl_forecast.retention import build_retention_plan, retention_status, validate_retention_plan


class Store:
    def __init__(self):
        self.objects = {
            "state/canonical-snapshot.json": {
                "schema_version": 1,
                "database_key": "snapshots/current.duckdb",
                "manifest_key": "snapshots/current.manifest.json",
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
        for competition_id in COMPETITION_IDS:
            self.objects[f"state/fits/{competition_id}.json"] = {
                "schema_version": 1,
                "database_key": f"fits/{competition_id}/current.duckdb",
            }
            self.objects[f"state/results/{competition_id}.json"] = {
                "schema_version": 1,
                "database_key": f"results/{competition_id}/current.duckdb",
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
                *(f"fits/{competition_id}/current.duckdb" for competition_id in COMPETITION_IDS),
                "fits/eng-premier-league/old.duckdb",
            ],
            "results/": [
                *(f"results/{competition_id}/current.duckdb" for competition_id in COMPETITION_IDS),
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

    def exists(self, key):
        return key in self.objects or any(key in rows for rows in self.rows.values())


def old_plan(store):
    return build_retention_plan(store, now=datetime(2026, 10, 1, tzinfo=UTC))


def test_retention_plan_protects_live_targets_and_only_lists_candidates():
    plan = old_plan(Store())
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
    plan = old_plan(Store())
    validate_retention_plan(plan, old_plan(Store()))
    changed = {**plan, "delete_candidates": plan["delete_candidates"][:-1]}
    with pytest.raises(ValueError, match="delete_candidates changed"):
        validate_retention_plan(changed, plan)


def test_retention_status_separates_billable_and_product_occupancy():
    plan = old_plan(Store())
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


def test_retention_plan_fails_closed_on_missing_pointer_or_target():
    store = Store()
    del store.objects["state/results/eng-league-two.json"]
    with pytest.raises(ValueError, match="Required retention pointers are absent"):
        old_plan(store)

    store = Store()
    store.rows["results/"].remove("results/eng-league-two/current.duckdb")
    with pytest.raises(ValueError, match="Protected retention targets are absent"):
        old_plan(store)


def test_recent_unpointed_generations_stay_inside_the_rollback_grace():
    store = Store()
    plan = build_retention_plan(store, now=datetime(2026, 9, 19, tzinfo=UTC))
    grace_keys = {row["key"] for row in plan["grace_protected"]}
    assert "results/eng-premier-league/old.duckdb" in grace_keys
    assert "snapshots/old.duckdb" in grace_keys
    assert "runs/forecasts/old/forecast.json" not in grace_keys
