from datetime import UTC, datetime

from test_publication import Store, sample_forecast

from epl_forecast.publication import (
    activate_publication,
    derive_forecast,
    load_policy,
    publish_documents,
)
from epl_forecast.record import realized_outcomes, rebuild_record, update_record

MATCH = "eng-premier-league:2026-2027:arsenal:chelsea"


def document(generated, forecast_id, p_home=0.5):
    forecast = sample_forecast(generated=generated)
    forecast["matches"][0].update(p_home=p_home, p_draw=(1 - p_home) / 2, p_away=(1 - p_home) / 2)
    return {**derive_forecast(forecast, forecast_id), "released_at": generated}


def test_realized_outcomes_reads_finished_fixtures():
    fixtures = [
        {"match_id": "a", "status": "finished", "home_goals": 2, "away_goals": 1},
        {"match_id": "b", "status": "finished", "home_goals": 1, "away_goals": 1},
        {"match_id": "c", "status": "finished", "home_goals": 0, "away_goals": 3},
        {"match_id": "d", "status": "scheduled", "home_goals": None, "away_goals": None},
    ]
    assert realized_outcomes(fixtures) == {"a": "H", "b": "D", "c": "A"}


def test_the_record_retains_only_the_last_pre_kickoff_forecast():
    documents = [
        document("2026-09-10T12:00:00+00:00", "2026-09-10T120000Z", 0.5),
        document("2026-09-12T06:00:00+00:00", "2026-09-12T060000Z", 0.6),
        document("2026-09-12T18:00:00+00:00", "2026-09-12T180000Z", 0.9),
    ]

    record = update_record(None, documents, {}, load_policy(), "now")

    assert record["unsettled"] == 1
    assert record["pending"][0]["forecast_id"] == "2026-09-12T060000Z"
    assert record["pending"][0]["p_home"] == 0.6
    assert record["pending"][0]["model_version"] == "v0.0"


def test_compute_before_kickoff_released_after_kickoff_is_not_eligible():
    candidate = document("2026-09-12T13:00:00+00:00", "late-release", 0.9)
    candidate["released_at"] = "2026-09-12T14:01:00+00:00"
    record = update_record(None, [candidate], {}, load_policy(), "now")
    assert record["pending"] == []
    assert record["unsettled"] == 0


def test_the_record_scores_a_result_without_reading_an_archive():
    pending = update_record(
        None,
        [document("2026-09-10T12:00:00+00:00", "2026-09-10T120000Z")],
        {},
        load_policy(),
        "first",
    )

    scored = update_record(pending, [], {MATCH: "H"}, load_policy(), "second")

    assert scored["unsettled"] == 0
    assert scored["pending"] == []
    assert scored["summary"]["overall"]["scored"] == 1
    assert scored["settled"][0]["outcome"] == "H"
    assert scored["updated_at"] == "second"


def test_a_sharper_forecast_scores_better():
    sharp = update_record(
        None,
        [document("2026-09-10T12:00:00+00:00", "sharp", 0.9)],
        {MATCH: "H"},
        load_policy(),
    )["summary"]["overall"]
    blunt = update_record(
        None,
        [document("2026-09-10T12:00:00+00:00", "blunt", 0.2)],
        {MATCH: "H"},
        load_policy(),
    )["summary"]["overall"]
    assert sharp["log_loss"] < blunt["log_loss"]
    assert sharp["brier"] < blunt["brier"]


def test_the_record_can_be_rebuilt_from_partitioned_archives():
    store = Store()
    policy = load_policy()
    publish_documents(
        store,
        [
            document("2026-09-10T12:00:00+00:00", "2026-09-10T120000Z", 0.5),
            document("2026-09-12T06:00:00+00:00", "2026-09-12T060000Z", 0.6),
        ],
        policy,
    )
    activate_publication(
        store,
        store.objects["deployments/desired.json"]["revision_id"],
        activated_at=datetime(2026, 9, 12, 7, tzinfo=UTC),
    )

    record = rebuild_record(store, {MATCH: "D"}, policy)

    assert record["settled"][0]["forecast_id"] == "2026-09-12T060000Z"
    assert record["settled"][0]["outcome"] == "D"


def test_private_commit_before_kickoff_and_public_activation_after_kickoff_is_ineligible():
    store = Store()
    policy = load_policy()
    publish_documents(
        store,
        [document("2026-09-12T13:00:00+00:00", "late-public-activation", 0.9)],
        policy,
    )
    activate_publication(
        store,
        store.objects["deployments/desired.json"]["revision_id"],
        activated_at=datetime(2026, 9, 12, 14, 1, tzinfo=UTC),
    )

    record = rebuild_record(store, {MATCH: "H"}, policy)

    assert "commitments/eng-premier-league/late-public-activation.json" in store.objects
    assert record["pending"] == []
    assert record["settled"] == []


def test_rebuild_does_not_invent_public_time_for_historical_forecasts():
    store = Store()
    policy = load_policy()
    publish_documents(
        store,
        [document("2026-09-10T12:00:00+00:00", "unknown-public-time", 0.5)],
        policy,
    )

    record = rebuild_record(store, {MATCH: "H"}, policy)

    assert record["pending"] == []
    assert record["settled"] == []
