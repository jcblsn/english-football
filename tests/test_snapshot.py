import json
from datetime import UTC, datetime

import pytest

from epl_forecast.datasets import Dataset, publish
from epl_forecast.snapshot import (
    SnapshotDataset,
    create_snapshot,
    restore_snapshot,
    snapshot_manifest_path,
    verify_snapshot,
)
from epl_forecast.snapshots import SQUAD, SnapshotIndex, snapshot, snapshot_rows
from epl_forecast.storage import file_hash

MATCH_ID = "eng-championship:2026-2027:home:away"


def evidence(retrieved_at, source="a"):
    return {
        "provider": "test",
        "retrieved_at": retrieved_at,
        "evidence_basis": "captured",
        "source_sha256": source * 64,
    }


def fixture(match_date="2026-09-20", status="scheduled", home_goals=None):
    return {
        "match_id": MATCH_ID,
        "competition_id": "eng-championship",
        "season_id": "2026-2027",
        "stage": "regular",
        "home_team_id": "home",
        "away_team_id": "away",
        "match_date": match_date,
        "kickoff_time": f"{match_date}T14:00:00+00:00",
        "status": status,
        "home_goals": home_goals,
        "away_goals": 0 if home_goals is not None else None,
    }


def make_snapshot(tmp_path, tables):
    workspace = tmp_path / "canonical"
    for request, rows in tables:
        publish(workspace, request, rows)
    source = Dataset(workspace=workspace)
    database = tmp_path / "canonical.duckdb"
    try:
        manifest = create_snapshot(source, database, source_revision="revision-1")
    finally:
        source.close()
    return database, manifest


def test_snapshot_reconstructs_a_correction_without_changing_the_old_revision(tmp_path):
    database, manifest = make_snapshot(
        tmp_path,
        [
            (
                evidence("2026-09-21T10:00:00+00:00"),
                {"fixtures": [fixture(status="finished", home_goals=1)]},
            ),
            (
                evidence("2026-09-22T10:00:00+00:00", "b"),
                {"fixtures": [fixture(status="finished", home_goals=2)]},
            ),
        ],
    )
    assert manifest["tables"]["fixtures"]["rows"] == 2
    old = SnapshotDataset(database, datetime(2026, 9, 21, 12, tzinfo=UTC))
    current = SnapshotDataset(database, datetime(2026, 9, 22, 12, tzinfo=UTC))
    try:
        assert old.matches()[0].home_goals == 1
        assert current.matches()[0].home_goals == 2
        assert old.provenance()["batches"] != current.provenance()["batches"]
    finally:
        old.close()
        current.close()


def test_snapshot_keeps_empty_scope_and_repeated_capture_receipts(tmp_path):
    first = snapshot(SQUAD, "home", endpoint="test", row_count=1, team_id="home")
    empty = snapshot(SQUAD, "home", endpoint="test", row_count=0, team_id="home")
    database, _ = make_snapshot(
        tmp_path,
        [
            (
                evidence("2026-09-18T10:00:00+00:00"),
                {
                    "source_snapshots": [first],
                    "memberships": [
                        {
                            "player_id": "player",
                            "team_id": "home",
                            "season_id": "2026-2027",
                            "competition_id": "eng-championship",
                            "basis": "captured_squad",
                        }
                    ],
                },
            ),
            (
                evidence("2026-09-18T11:00:00+00:00"),
                {"source_snapshots": [empty]},
            ),
            (
                evidence("2026-09-18T12:00:00+00:00"),
                {"source_snapshots": [empty]},
            ),
        ],
    )
    data = SnapshotDataset(database)
    try:
        rows = snapshot_rows(data)
        index = SnapshotIndex(rows)
        assert len(rows) == 3
        assert len({row["source_sha256"] for row in rows}) == 1
        assert index.snapshot(SQUAD, "home")["row_count"] == 0
        assert (
            index.select(data.rows("SELECT * FROM memberships_observations"), SQUAD, "home") == []
        )
    finally:
        data.close()


def test_snapshot_preserves_conflicts_and_stable_fixture_identity(tmp_path):
    database, _ = make_snapshot(
        tmp_path,
        [
            (
                evidence("2026-09-18T10:00:00+00:00"),
                {"fixtures": [fixture("2026-09-20")]},
            ),
            (
                evidence("2026-09-18T11:00:00+00:00", "b"),
                {"fixtures": [fixture("2026-09-27")]},
            ),
        ],
    )
    old = SnapshotDataset(database, datetime(2026, 9, 18, 10, 30, tzinfo=UTC))
    current = SnapshotDataset(database)
    try:
        assert old.fixtures()[0]["match_id"] == MATCH_ID
        assert current.fixtures()[0]["match_id"] == MATCH_ID
        assert str(old.fixtures()[0]["match_date"]) == "2026-09-20"
        assert str(current.fixtures()[0]["match_date"]) == "2026-09-27"
    finally:
        old.close()
        current.close()

    conflict_workspace = tmp_path / "conflict"
    publish(
        conflict_workspace,
        evidence("2026-09-18T10:00:00+00:00"),
        {"fixtures": [fixture(status="finished", home_goals=1)]},
    )
    publish(
        conflict_workspace,
        {**evidence("2026-09-18T11:00:00+00:00", "c"), "provider": "other"},
        {"fixtures": [fixture(status="finished", home_goals=2)]},
    )
    source = Dataset(workspace=conflict_workspace)
    conflict = tmp_path / "conflict.duckdb"
    try:
        create_snapshot(source, conflict, source_revision="revision-conflict")
    finally:
        source.close()
    data = SnapshotDataset(conflict)
    try:
        with pytest.raises(ValueError, match="Contradictory"):
            data.fixtures()
    finally:
        data.close()


def test_restore_checks_the_complete_file_before_replacing_a_local_copy(tmp_path):
    database, manifest = make_snapshot(
        tmp_path / "owner's evidence",
        [(evidence("2026-09-18T10:00:00+00:00"), {"fixtures": [fixture()]})],
    )
    restored = tmp_path / "local" / "current.duckdb"
    restored.parent.mkdir()
    restored.write_bytes(b"last good local revision")
    restore_snapshot(database, restored)
    assert file_hash(restored) == manifest["database_sha256"]
    assert (
        verify_snapshot(restored, snapshot_manifest_path(database))["data_revision"]
        == manifest["data_revision"]
    )

    damaged = tmp_path / "damaged.duckdb"
    damaged.write_bytes(database.read_bytes() + b"damage")
    damaged_manifest = snapshot_manifest_path(damaged)
    damaged_manifest.write_text(json.dumps(manifest))
    last_good = restored.read_bytes()
    with pytest.raises(ValueError, match="byte count"):
        restore_snapshot(damaged, restored)
    assert restored.read_bytes() == last_good
