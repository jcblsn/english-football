from datetime import UTC, datetime

from epl_forecast.data.capture import retain
from epl_forecast.datasets import publish
from epl_forecast.pipeline import information_fingerprint


def test_normalize_rejects_corrupted_raw_capture(tmp_path):
    import pytest

    from epl_forecast.data.collect import normalize

    record = retain(
        tmp_path, "fpl", "https://example.test", b"{}", "2026-09-08T00:00:00+00:00", "prospective"
    )
    (tmp_path / record["raw_path"]).write_bytes(b"modified")
    with pytest.raises(ValueError, match="hash mismatch"):
        normalize(tmp_path)


def test_final_fixture_capture_has_bounded_correction_checkpoints():
    from datetime import timedelta

    from epl_forecast.data.collect import fixture_details_due

    kickoff = datetime(2026, 9, 1, 15, tzinfo=UTC)
    fixtures = [{"fixture": {"id": 10, "date": kickoff.isoformat(), "status": {"short": "FT"}}}]

    def records(hours):
        return [
            {
                "provider": "api_football",
                "context": {"endpoint": "fixtures", "ids": "10-11"},
                "retrieved_at": (kickoff + timedelta(hours=hours)).isoformat(),
            }
        ]

    assert fixture_details_due(fixtures, [], kickoff + timedelta(hours=3)) == [10]
    assert fixture_details_due(fixtures, records(3), kickoff + timedelta(hours=4)) == []
    assert fixture_details_due(fixtures, records(3), kickoff + timedelta(days=1)) == [10]
    assert fixture_details_due(fixtures, records(25), kickoff + timedelta(days=2)) == []
    assert fixture_details_due(fixtures, records(25), kickoff + timedelta(days=7)) == [10]
    assert fixture_details_due(fixtures, records(169), kickoff + timedelta(days=30)) == []


def test_market_snapshot_changes_forecast_fingerprint(tmp_path):
    from epl_forecast.datasets import Dataset

    before = Dataset(tmp_path)
    try:
        first = information_fingerprint(before)
    finally:
        before.close()
    publish(
        tmp_path,
        {
            "provider": "football_data",
            "retrieved_at": "2026-09-09T12:00:00+00:00",
            "evidence_basis": "prospective",
            "source_sha256": "b" * 64,
            "context": {},
        },
        {
            "odds": [
                {
                    "match_id": "match",
                    "competition_id": "eng-premier-league",
                    "season_id": "2026-2027",
                    "family": "market_average_preclosing",
                    "home_odds": 2,
                    "draw_odds": 3,
                    "away_odds": 4,
                }
            ]
        },
    )
    after = Dataset(tmp_path)
    try:
        second = information_fingerprint(after)
    finally:
        after.close()
    assert first != second


def test_retrieval_time_alone_does_not_change_the_forecast_fingerprint(tmp_path):
    from epl_forecast.datasets import Dataset

    odds = {
        "match_id": "match",
        "competition_id": "eng-premier-league",
        "season_id": "2026-2027",
        "family": "market_average_preclosing",
        "home_odds": 2,
        "draw_odds": 3,
        "away_odds": 4,
    }
    request = {
        "provider": "football_data",
        "retrieved_at": "2026-09-09T12:00:00+00:00",
        "evidence_basis": "prospective",
        "source_sha256": "a" * 64,
        "context": {},
    }
    publish(tmp_path, request, {"odds": [odds]})
    before = Dataset(tmp_path)
    try:
        first = information_fingerprint(before)
    finally:
        before.close()
    publish(
        tmp_path,
        {
            **request,
            "retrieved_at": "2026-09-10T12:00:00+00:00",
            "source_sha256": "b" * 64,
        },
        {"odds": [odds]},
    )
    after = Dataset(tmp_path)
    try:
        assert information_fingerprint(after) == first
    finally:
        after.close()
