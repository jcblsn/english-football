from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from epl_forecast.datasets import publish
from epl_forecast.pipeline import information_fingerprint

COMPETITION = "eng-premier-league"


def scheduled_fixture(competition=COMPETITION):
    return {
        "match_id": f"{competition}:2026-2027:arsenal:chelsea",
        "competition_id": competition,
        "season_id": "2026-2027",
        "stage": "regular",
        "home_team_id": "arsenal",
        "away_team_id": "chelsea",
        "match_date": "2026-09-12",
        "kickoff_time": "2026-09-12T14:00:00+00:00",
        "status": "scheduled",
        "home_goals": None,
        "away_goals": None,
    }


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
    assert fixture_details_due(fixtures, records(25), kickoff + timedelta(days=3)) == [10]
    assert fixture_details_due(fixtures, records(73), kickoff + timedelta(days=4)) == []
    assert fixture_details_due(fixtures, records(73), kickoff + timedelta(days=7)) == [10]
    assert fixture_details_due(fixtures, records(169), kickoff + timedelta(days=30)) == []


def test_fixture_details_capture_lineups_before_kickoff():
    from epl_forecast.data.collect import fixture_details_due

    kickoff = datetime(2026, 9, 19, 14, tzinfo=UTC)
    fixtures = [{"fixture": {"id": 10, "date": kickoff.isoformat(), "status": {"short": "NS"}}}]

    def records(minutes):
        return [
            {
                "provider": "api_football",
                "context": {"endpoint": "fixtures", "ids": "10"},
                "retrieved_at": (kickoff + timedelta(minutes=minutes)).isoformat(),
            }
        ]

    assert fixture_details_due(fixtures, [], kickoff - timedelta(minutes=80)) == []
    assert fixture_details_due(fixtures, [], kickoff - timedelta(minutes=70)) == [10]
    assert fixture_details_due(fixtures, records(-70), kickoff - timedelta(minutes=65)) == []
    assert fixture_details_due(fixtures, records(-70), kickoff - timedelta(minutes=60)) == [10]
    assert fixture_details_due(fixtures, records(-10), kickoff - timedelta(minutes=1)) == [10]
    fixtures[0]["fixture"]["status"]["short"] = "2H"
    assert fixture_details_due(fixtures, records(-1), kickoff + timedelta(minutes=50)) == []
    assert fixture_details_due(fixtures, records(-1), kickoff + timedelta(minutes=70)) == [10]


def test_collection_readiness_reports_delayed_inputs_without_a_gate(monkeypatch):
    from epl_forecast import personnel
    from epl_forecast.data.collect import collection_readiness

    now = datetime(2026, 9, 16, 12, tzinfo=UTC)
    old = {
        **scheduled_fixture(),
        "match_id": "old",
        "kickoff_time": now - timedelta(days=4),
        "status": "finished",
    }
    uncovered = {
        **scheduled_fixture(),
        "match_id": "uncovered",
        "kickoff_time": now + timedelta(days=2),
    }
    covered = {
        **scheduled_fixture(),
        "match_id": "covered",
        "kickoff_time": now + timedelta(days=3),
    }

    class Data:
        def fixtures(self):
            return [old, uncovered, covered]

        def rows(self, sql, parameters=None):
            if "FROM team_statistics" in sql:
                return [{"match_id": "old", "teams": 1}]
            if "FROM odds" in sql:
                return [{"match_id": "covered"}]
            raise AssertionError(sql)

    evidence = SimpleNamespace(
        injuries={
            ("uncovered", "arsenal", "player"): [{"status": "unavailable", "reason": "Injury"}]
        },
        fpl={"player": {"team_id": "arsenal", "status": "a"}},
    )
    monkeypatch.setattr(personnel, "load_availability_evidence", lambda *_: {})
    monkeypatch.setattr(personnel, "Evidence", lambda *_args, **_kwargs: evidence)

    report = collection_readiness(Data(), now)

    assert report["informational_only"] is True
    assert report["status"] == "available"
    assert report["settled_finished_matches"] == 1
    assert report["finished_matches_missing_xg"] == 1
    assert report["upcoming_premier_league_matches"] == 2
    assert report["upcoming_matches_without_market_data"] == 1
    assert report["personnel_source_disagreements"] == 1


def test_market_snapshot_changes_forecast_fingerprint(tmp_path):
    from epl_forecast.datasets import Dataset

    before = Dataset(workspace=tmp_path)
    try:
        first = information_fingerprint(before, COMPETITION)
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
            "fixtures": [scheduled_fixture()],
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
            ],
        },
    )
    after = Dataset(workspace=tmp_path)
    try:
        second = information_fingerprint(after, COMPETITION)
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
    publish(tmp_path, request, {"fixtures": [scheduled_fixture()], "odds": [odds]})
    before = Dataset(workspace=tmp_path)
    try:
        first = information_fingerprint(before, COMPETITION)
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
    after = Dataset(workspace=tmp_path)
    try:
        assert information_fingerprint(after, COMPETITION) == first
    finally:
        after.close()


def test_unused_availability_does_not_change_the_forecast_fingerprint(tmp_path):
    from epl_forecast.datasets import Dataset

    request = {
        "provider": "fpl",
        "retrieved_at": "2026-09-09T12:00:00+00:00",
        "evidence_basis": "prospective",
        "source_sha256": "a" * 64,
        "context": {},
    }
    before = Dataset(workspace=tmp_path)
    try:
        first = information_fingerprint(before, COMPETITION)
    finally:
        before.close()
    publish(
        tmp_path,
        request,
        {
            "availability": [
                {
                    "player_id": "player",
                    "team_id": "arsenal",
                    "competition_id": COMPETITION,
                    "season_id": "2026-2027",
                    "scope": "current",
                    "status": "injured",
                    "reason": "Test",
                }
            ]
        },
    )
    after = Dataset(workspace=tmp_path)
    try:
        assert information_fingerprint(after, COMPETITION) == first
    finally:
        after.close()


def test_one_competition_schedule_does_not_change_another_fingerprint(tmp_path):
    from epl_forecast.datasets import Dataset

    before = Dataset(workspace=tmp_path)
    try:
        first = information_fingerprint(before, COMPETITION)
    finally:
        before.close()
    publish(
        tmp_path,
        {
            "provider": "api_football",
            "retrieved_at": "2026-09-09T12:00:00+00:00",
            "evidence_basis": "prospective",
            "source_sha256": "c" * 64,
            "context": {},
        },
        {"fixtures": [scheduled_fixture("eng-league-two")]},
    )
    after = Dataset(workspace=tmp_path)
    try:
        assert information_fingerprint(after, COMPETITION) == first
    finally:
        after.close()
