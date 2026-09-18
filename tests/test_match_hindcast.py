from datetime import date, datetime

import pytest
from test_publication import Store

from epl_forecast import match_hindcast
from epl_forecast.live import LONDON
from epl_forecast.match_hindcast import (
    INDEX_KEY,
    boundary,
    derive_match_hindcast,
    document_key,
    index_entry,
    origin_at,
    prospective_start,
    publish_index,
    season_of,
)
from epl_forecast.models.baselines import AttackDefensePoisson
from epl_forecast.publication import check_publishable, document_kind, load_policy
from epl_forecast.record import update_record
from epl_forecast.storage import json_bytes

HANDOFF = {"prospective_from": "2026-09-17", "last_match_date": "2026-09-16"}


def archive_store(generated, model_version="v0.3.0"):
    store = Store()
    for competition_id, moment in generated.items():
        store.objects[f"forecasts/{competition_id}/archive.json"] = {
            "schema_version": 1,
            "competition_id": competition_id,
            "updated_at": moment,
            "forecasts": [
                {"forecast_id": "2026-09-15T003839Z", "generated_at": "2026-09-15T00:39:44+00:00"},
                {
                    "forecast_id": "2026-09-17T144601Z",
                    "generated_at": moment,
                    "model_version": model_version,
                },
            ],
        }
    return store


def row(
    match_id="eng-premier-league:2026-2027:arsenal:chelsea", match_date="2026-08-15", shift=-0.08
):
    return {
        "match_id": match_id,
        "match_date": match_date,
        "kickoff_time": datetime.fromisoformat(f"{match_date}T14:00:00+00:00"),
        "home_team_id": "arsenal",
        "away_team_id": "chelsea",
        "origin_at": origin_at(date.fromisoformat(match_date)).isoformat(),
        "model_results_cutoff": match_date,
        "training_matches": 900,
        "p_home": 0.5,
        "p_draw": 0.25,
        "p_away": 0.25,
        "unadjusted": {"p_home": 0.52, "p_draw": 0.24, "p_away": 0.24},
        "personnel": None
        if shift is None
        else {
            "home": {"discontinuity": 0.1, "unresolved_weight": 0.0},
            "away": {"discontinuity": 0.3, "unresolved_weight": 0.0},
            "home_log_rate_shift": shift,
        },
        "score_distribution": {
            "home_rate": 1.6,
            "away_rate": 1.2,
            "omitted_probability": 0.2,
            "grid_home_rows_away_columns": [[0.5, 0.2], [0.1, 0.0]],
        },
    }


def test_the_origin_is_midnight_in_london_on_the_day_of_the_match():
    summer = origin_at(date(2026, 8, 15))
    winter = origin_at(date(2026, 12, 5))
    assert summer.isoformat() == "2026-08-15T00:00:00+01:00"
    assert winter.isoformat() == "2026-12-05T00:00:00+00:00"
    assert summer.tzinfo is LONDON


def test_the_handoff_is_the_first_london_day_of_live_coverage_of_the_version():
    store = archive_store(
        {
            "eng-premier-league": "2026-09-17T14:56:47+00:00",
            "eng-championship": "2026-09-17T15:06:49+00:00",
            "eng-league-one": "2026-09-17T15:15:49+00:00",
            "eng-league-two": "2026-09-17T15:24:43+00:00",
        }
    )
    assert prospective_start(store, "v0.3.0") == date(2026, 9, 17)
    assert boundary(store, "v0.3.0") == HANDOFF
    assert prospective_start(store, "v0.2") is None


def test_the_handoff_day_is_a_london_day_not_a_utc_day():
    store = archive_store({"eng-premier-league": "2026-09-16T23:30:00+00:00"})
    assert boundary(store, "v0.3.0") == HANDOFF


def test_a_version_with_no_published_forecast_has_no_bridge():
    with pytest.raises(ValueError, match="No published forecast"):
        boundary(Store(), "v0.9.0")


def test_a_match_hindcast_is_retrospective_and_publishable():
    document = derive_match_hindcast("v0.3.0", "eng-premier-league", "2026-2027", [row()], HANDOFF)
    check_publishable(document, load_policy())
    assert document_kind(document) == "match_hindcast"
    assert document["retrospective"] is True
    assert document["prospective_from"] == "2026-09-17"
    assert document["last_match_date"] == "2026-08-15"
    match = document["matches"][0]
    assert match["origin_at"] == "2026-08-15T00:00:00+01:00"
    assert match["model_results_cutoff"] == "2026-08-15"
    assert match["personnel"] == {
        "home_discontinuity": 0.1,
        "away_discontinuity": 0.3,
        "home_log_rate_shift": -0.08,
    }
    assert match["unadjusted"] == {"p_home": 0.52, "p_draw": 0.24, "p_away": 0.24}
    assert match["score_probabilities"]["grid_home_rows_away_columns"] == [[0.5, 0.2], [0.1, 0.0]]


def test_a_match_hindcast_without_the_personnel_adjustment_says_so():
    document = derive_match_hindcast(
        "v0.3.0", "eng-league-two", "2026-2027", [row(shift=None)], HANDOFF
    )
    check_publishable(document, load_policy())
    assert document["matches"][0]["personnel"] is None


def test_a_match_hindcast_cannot_reach_prospective_coverage():
    with pytest.raises(ValueError, match="not before the prospective coverage"):
        derive_match_hindcast(
            "v0.3.0", "eng-premier-league", "2026-2027", [row(match_date="2026-09-17")], HANDOFF
        )
    with pytest.raises(ValueError, match="No retrospective matches"):
        derive_match_hindcast("v0.3.0", "eng-premier-league", "2026-2027", [], HANDOFF)


def test_a_match_hindcast_cannot_enter_the_prospective_record():
    document = derive_match_hindcast("v0.3.0", "eng-premier-league", "2026-2027", [row()], HANDOFF)
    with pytest.raises(ValueError, match="cannot enter the prospective record"):
        update_record(None, [document], {}, load_policy())


def test_the_index_points_at_one_document_for_each_version_division_and_season():
    store = Store()
    policy = load_policy()
    document = derive_match_hindcast(
        "v0.3.0", "eng-premier-league", "2026-2027", [row(), row(match_date="2026-08-22")], HANDOFF
    )
    entry = index_entry(document)
    assert entry == {
        "model_version": "v0.3.0",
        "competition_id": "eng-premier-league",
        "competition_name": "Premier League",
        "season_id": "2026-2027",
        "match_count": 2,
        "first_match_date": "2026-08-15",
        "last_match_date": "2026-08-22",
        "prospective_from": "2026-09-17",
        "href": "match-hindcasts/v0.3.0/eng-premier-league/2026-2027.json",
    }
    index = publish_index(store, [entry], policy)
    check_publishable(index, policy)
    assert document_kind(index) == "match_hindcast_index"
    assert index["seasons"] == [entry]
    assert store.objects[INDEX_KEY] == index
    assert publish_index(store, [entry], policy)["updated_at"] == index["updated_at"]


def test_the_season_of_the_bridge_follows_the_english_calendar():
    assert season_of(date(2026, 9, 16)) == "2026-2027"
    assert season_of(date(2027, 5, 20)) == "2026-2027"
    assert document_key("v0.3.0", "eng-championship", "2026-2027") == (
        "match-hindcasts/v0.3.0/eng-championship/2026-2027.json"
    )


def test_the_private_run_and_the_public_document_are_json(tmp_path):
    document = derive_match_hindcast("v0.3.0", "eng-premier-league", "2026-2027", [row()], HANDOFF)
    json_bytes(document)
    json_bytes({**HANDOFF, "matches": [{**row(), "kickoff_time": "2026-08-15T14:00:00+00:00"}]})


def test_a_match_forecast_uses_only_results_available_before_its_london_day(full_season):
    def fitted(matches, config, model_id, as_of):
        training = [match for match in matches if match.available_on <= as_of]
        return AttackDefensePoisson().fit(training, as_of), {}, training

    def stages(prediction, max_goals, shift=None, quote=None, market_pool=None):
        stage = {
            "p_home": 0.5,
            "p_draw": 0.25,
            "p_away": 0.25,
            "score_distribution": {
                "home_rate": 1.5,
                "away_rate": 1.1,
                "omitted_probability": 0.0,
                "grid_home_rows_away_columns": [[1.0]],
            },
        }
        return {"unadjusted": stage, "personnel_adjusted": stage}, None, (0.5, 0.25, 0.25), None

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(match_hindcast, "fitted_model", fitted)
    monkeypatch.setattr(match_hindcast, "forecast_probability_stages", stages)
    try:
        day = full_season[200].fixture.match_date
        targets = [
            match.fixture.match_id for match in full_season if match.fixture.match_date == day
        ]
        match_hindcast._initialize(
            full_season,
            [],
            {"rows": {}, "histories": {}, "kickoffs": {}},
            {match.fixture.match_id: None for match in full_season},
        )
        rows = match_hindcast.forecast_day(
            {
                "competition_id": "eng-premier-league",
                "match_date": str(day),
                "matches": sorted(targets),
            }
        )
    finally:
        monkeypatch.undo()
    earlier = sum(1 for match in full_season if match.available_on <= day)
    assert len(rows) == len(targets)
    assert {result["training_matches"] for result in rows} == {earlier}
    assert {result["model_results_cutoff"] for result in rows} == {str(day)}
    assert all(result["origin_at"].startswith(f"{day}T00:00:00") for result in rows)
