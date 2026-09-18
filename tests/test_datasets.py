from datetime import UTC, datetime

import duckdb
import pytest

from epl_forecast.datasets import Dataset, publish


def evidence(time="2026-09-08T12:00:00+00:00"):
    return {
        "provider": "test",
        "retrieved_at": time,
        "evidence_basis": "retrospective",
        "source_sha256": "a" * 64,
        "context": {},
    }


def fixture(goals=1):
    return {
        "match_id": "eng-premier-league:2025-2026:a:b",
        "competition_id": "eng-premier-league",
        "season_id": "2025-2026",
        "home_team_id": "a",
        "away_team_id": "b",
        "match_date": "2025-08-10",
        "stage": "regular",
        "status": "finished",
        "home_goals": goals,
        "away_goals": 0,
    }


def test_publication_is_deterministic_and_cutoff_does_not_backdate(tmp_path):
    manifest = publish(tmp_path, evidence(), {"fixtures": [fixture()]})
    assert publish(tmp_path, evidence(), {"fixtures": [fixture()]}) == manifest
    data = Dataset(workspace=tmp_path)
    assert len(data.matches()) == 1
    data.verify()
    data.close()
    old = Dataset(datetime(2025, 8, 11, tzinfo=UTC), workspace=tmp_path)
    assert not old.matches()
    old.close()


def test_unpublished_files_are_invisible_and_corruption_is_detected(tmp_path):
    manifest = publish(tmp_path, evidence(), {"fixtures": [fixture()]})
    path = tmp_path / manifest["files"][0]["path"]
    path.write_bytes(b"corrupted")
    with pytest.raises((duckdb.Error, ValueError)):
        data = Dataset(workspace=tmp_path)
        data.verify()
    (tmp_path / "manifests" / (manifest["batch_id"] + ".json")).unlink()
    data = Dataset(workspace=tmp_path)
    assert not data.matches()
    data.close()


def test_duplicate_rows_and_provider_contradictions_fail(tmp_path):
    with pytest.raises(ValueError, match="duplicate"):
        publish(tmp_path, evidence(), {"fixtures": [fixture(), fixture(2)]})
    publish(tmp_path, evidence(), {"fixtures": [fixture()]})
    other = {**evidence(), "provider": "other"}
    publish(tmp_path, other, {"fixtures": [fixture(2)]})
    data = Dataset(workspace=tmp_path)
    with pytest.raises(ValueError, match="Contradictory"):
        data.matches()
    data.close()


def test_a_disputed_record_yields_to_the_finished_one(tmp_path):
    publish(tmp_path, evidence(), {"fixtures": [fixture()]})
    disputed = {**fixture(), "status": "disputed", "match_date": None, "home_goals": None}
    disputed["away_goals"] = None
    publish(tmp_path, {**evidence(), "provider": "api_football"}, {"fixtures": [disputed]})
    data = Dataset(workspace=tmp_path)
    (match,) = data.matches()
    data.close()
    assert (str(match.fixture.match_date), match.home_goals, match.away_goals) == (
        "2025-08-10",
        1,
        0,
    )


def test_stored_times_read_back_in_utc(tmp_path):
    kickoff = "2025-08-10T19:00:00+00:00"
    publish(tmp_path, evidence(), {"fixtures": [{**fixture(), "kickoff_time": kickoff}]})
    data = Dataset(workspace=tmp_path)
    zone = data.rows("SELECT current_setting('TimeZone') AS zone")[0]["zone"]
    (row,) = data.rows("SELECT kickoff_time FROM fixtures")
    data.close()
    assert zone == "UTC"
    assert row["kickoff_time"].isoformat() == kickoff


def test_unscoped_history_keeps_unknown_end_date(tmp_path):
    publish(
        tmp_path,
        evidence(),
        {
            "availability": [
                {
                    "player_id": "p1",
                    "scope": "interval",
                    "status": "sidelined",
                    "start_date": "2024-01-01",
                    "end_date": None,
                }
            ]
        },
    )
    data = Dataset(workspace=tmp_path)
    rows = data.rows("SELECT * FROM availability")
    assert len(rows) == 1 and rows[0]["end_date"] is None
    data.close()


def test_a_narrowed_dataset_registers_only_the_tables_a_reader_asked_for(tmp_path):
    """Registering a table costs one request for each of its Parquet files."""
    publish(
        tmp_path,
        {
            "provider": "api_football",
            "retrieved_at": "2026-09-18T10:00:00+00:00",
            "evidence_basis": "captured",
            "source_sha256": "a" * 64,
        },
        {
            "teams": [{"team_id": "arsenal", "name": "Arsenal"}],
            "fixtures": [
                {
                    "match_id": "eng-premier-league:2026-2027:arsenal:chelsea",
                    "competition_id": "eng-premier-league",
                    "season_id": "2026-2027",
                    "stage": "regular",
                    "home_team_id": "arsenal",
                    "away_team_id": "chelsea",
                    "match_date": "2026-09-20",
                    "status": "scheduled",
                }
            ],
        },
    )
    data = Dataset(workspace=tmp_path, tables=("fixtures",))
    try:
        assert data.rows("SELECT count(*) AS n FROM fixtures") == [{"n": 1}]
        with pytest.raises(duckdb.CatalogException):
            data.rows("SELECT count(*) AS n FROM teams")
    finally:
        data.close()
