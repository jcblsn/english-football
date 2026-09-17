from copy import deepcopy

import duckdb

from epl_forecast.data.api_football import match_player_statistics
from epl_forecast.datasets import Dataset, publish
from epl_forecast.storage import file_hash, write_json


def test_rich_player_statistics_preserve_missing_zero_and_raw_accuracy():
    statistics = {
        "games": {"rating": "7.2"},
        "passes": {"total": 35, "key": 0, "accuracy": "27"},
        "duels": {"total": 4, "won": 2},
        "dribbles": {"attempts": None, "success": None},
    }
    original = deepcopy(statistics)
    issues = []
    row = match_player_statistics(statistics, {"player_id": "p1"}, issues)
    assert row["rating"] == 7.2 and row["key_passes"] == 0
    assert row["pass_accuracy"] == "27"
    assert row["tackles"] is None and row["dribbles_attempted"] is None
    assert statistics == original and not issues


def test_inconsistent_or_invalid_statistics_are_unknown_with_audit():
    issues = []
    row = match_player_statistics(
        {
            "games": {"rating": "nan"},
            "passes": {"total": -1, "key": 0},
            "duels": {"total": 2, "won": 4},
            "fouls": {"drawn": 0.5},
        },
        {"player_id": "p1"},
        issues,
    )
    assert row["rating"] is row["passes_total"] is row["duels_total"] is row["duels_won"] is None
    assert len(issues) == 4
    assert issues[-1]["reported_values"] == [2, 4]


def test_legacy_partitions_have_typed_nulls_and_replay_version_wins(tmp_path):
    record = {
        "provider": "api_football",
        "retrieved_at": "2026-09-09T12:00:00+00:00",
        "evidence_basis": "retrospective",
        "source_sha256": "a" * 64,
    }
    legacy = tmp_path / "parquet" / "appearances" / "legacy.parquet"
    legacy.parent.mkdir(parents=True)
    with duckdb.connect() as con:
        con.execute(
            "COPY (SELECT 'm1' AS match_id, 'p1' AS player_id, 'arsenal' AS team_id, "
            "'api_football' AS provider, '2026-09-09T12:00:00Z'::TIMESTAMPTZ AS retrieved_at, "
            "repeat('a', 64) AS source_sha256, 90 AS minutes) TO ? (FORMAT PARQUET)",
            [str(legacy)],
        )
    write_json(
        tmp_path / "manifests" / "legacy.json",
        {
            "batch_id": "legacy",
            "request": record,
            "files": [
                {
                    "table": "appearances",
                    "path": str(legacy.relative_to(tmp_path)),
                    "sha256": file_hash(legacy),
                }
            ],
        },
    )
    data = Dataset(workspace=tmp_path)
    assert data.rows("SELECT rating, tackles FROM appearances") == [
        {"rating": None, "tackles": None}
    ]
    data.close()
    publish(
        tmp_path,
        {**record, "normalization_version": 2},
        {
            "appearances": [
                {
                    "match_id": "m1",
                    "player_id": "p1",
                    "team_id": "arsenal",
                    "minutes": 90,
                    "rating": 7.5,
                }
            ]
        },
    )
    data = Dataset(workspace=tmp_path)
    assert data.rows("SELECT rating, tackles FROM appearances") == [
        {"rating": 7.5, "tackles": None}
    ]
    assert data.rows("SELECT count(*) AS n FROM appearances_observations") == [{"n": 2}]
    data.close()
