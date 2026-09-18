from epl_forecast.retention import build_retention_plan


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
