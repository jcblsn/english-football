import json

import pytest

from epl_forecast.publication import (
    check_publishable,
    derive_forecast,
    empty_index,
    load_policy,
    materialize_publication,
    publish_document,
    publish_documents_to_store,
    rebuild_index,
)


def sample_forecast(competition="eng-premier-league", generated="2026-09-10T12:00:00+00:00"):
    return {
        "competition_id": competition,
        "competition_name": "Premier League",
        "season_id": "2026-2027",
        "generated_at": generated,
        "state_observed_at": "2026-09-10T11:00:00+00:00",
        "model_results_cutoff": "2026-09-10",
        "state_uncertainty": "posterior",
        "model": {"id": "M7-xg-v1", "kind": "bayesian_xg_quality_tilt", "parameters": {}},
        "team_names": {"arsenal": "Arsenal", "chelsea": "Chelsea"},
        "team_strengths": [{"team_id": "arsenal", "quality": 0.4}],
        "sources": [{"name": "api_football", "sha256": "a" * 64}],
        "matches": [
            {
                "match_id": "eng-premier-league:2026-2027:arsenal:chelsea",
                "kickoff_time": "2026-09-12T14:00:00+00:00",
                "match_date": "2026-09-12",
                "home_team_id": "arsenal",
                "away_team_id": "chelsea",
                "status": "scheduled",
                "p_home": 0.5,
                "p_draw": 0.25,
                "p_away": 0.25,
                "primary_probability_source": "structural",
                "next_match_for_teams": ["arsenal", "chelsea"],
                "market_assisted_probabilities": {
                    "p_home": 0.48,
                    "p_draw": 0.26,
                    "p_away": 0.26,
                    "decimal_odds": {"home": 2.0, "draw": 3.5, "away": 4.0},
                    "market_family": "closing",
                    "market_observed_at": "2026-09-11T00:00:00+00:00",
                },
                "score_distribution": {
                    "home_rate": 1.6,
                    "away_rate": 1.1,
                    "omitted_probability": 0.0,
                    "grid_home_rows_away_columns": [[0.5, 0.25], [0.15, 0.1]],
                },
            },
            {
                "match_id": "eng-premier-league:2026-2027:chelsea:arsenal",
                "kickoff_time": "2026-12-12T14:00:00+00:00",
                "match_date": "2026-12-12",
                "home_team_id": "chelsea",
                "away_team_id": "arsenal",
                "status": "scheduled",
                "p_home": 0.4,
                "p_draw": 0.3,
                "p_away": 0.3,
                "primary_probability_source": "structural",
                "next_match_for_teams": [],
                "market_assisted_probabilities": None,
                "score_distribution": {
                    "home_rate": 1.4,
                    "away_rate": 1.3,
                    "omitted_probability": 0.0,
                    "grid_home_rows_away_columns": [[0.5, 0.25], [0.15, 0.1]],
                },
            },
        ],
        "simulation": {
            "simulations": 10000,
            "teams": [
                {
                    "team_id": "arsenal",
                    "played": 3,
                    "current_points": 9,
                    "mean_points": 80.5,
                    "median_points": 80,
                    "points_intervals": {"50": [70, 90], "80": [65, 95], "90": [60, 97]},
                    "points_quantiles_05_50_95": [60.0, 80.0, 97.00000000001],
                    "mean_position": 1.5,
                    "median_position": 1,
                    "position_sd": 0.5,
                    "position_intervals": {"50": [1, 2], "80": [1, 2], "90": [1, 2]},
                    "mean_goal_difference": 30.0,
                    "position_probabilities": [0.5, 0.5],
                    "points_distribution": {"80": 0.5, "81": 0.5, "82": 1e-9},
                    "goal_difference_distribution": {"30": 1.0},
                    "title_probability": 0.5,
                    "relegation_probability": 0.0,
                },
                {
                    "team_id": "chelsea",
                    "played": 3,
                    "current_points": 4,
                    "mean_points": 60.5,
                    "median_points": 60,
                    "points_intervals": {"50": [50, 70], "80": [45, 75], "90": [40, 77]},
                    "points_quantiles_05_50_95": [40.0, 60.0, 77.0],
                    "mean_position": 2.5,
                    "median_position": 2,
                    "position_sd": 0.5,
                    "position_intervals": {"50": [1, 2], "80": [1, 2], "90": [1, 2]},
                    "mean_goal_difference": 5.0,
                    "position_probabilities": [0.5, 0.5],
                    "points_distribution": {"60": 0.5, "61": 0.5},
                    "goal_difference_distribution": {"5": 1.0},
                    "title_probability": 0.5,
                    "relegation_probability": 0.0,
                },
            ],
        },
    }


def sample_run():
    return {
        "package_version": "0.1.0",
        "code_sha256": "b" * 64,
        "execution": {"commit": "c" * 40},
        "data_manifest": {"files": ["data/parquet/fixtures.parquet"]},
    }


def test_policy_allowlist_respects_the_boundary():
    policy = load_policy()
    forbidden = policy["boundary"]["forbidden_key_substrings"]
    assert not [
        key
        for key in policy["surface"]["allowed_keys"]
        if any(substring in key for substring in forbidden)
    ]


def test_derived_forecast_drops_provider_evidence():
    document = derive_forecast(sample_forecast(), sample_run(), "2026-09-10T120000Z")
    check_publishable(document, load_policy())
    text = json.dumps(document)
    assert "decimal_odds" not in text
    assert "api_football" not in text
    assert "parquet" not in text
    assert document["matches"][0]["market_assisted"] == {
        "p_home": 0.48,
        "p_draw": 0.26,
        "p_away": 0.26,
    }
    assert document["model"] == {"version": "v0.0"}
    assert "M7" not in text
    assert "code_sha256" not in text
    assert "verification" not in text


def test_derived_forecast_keeps_the_distributional_surface():
    document = derive_forecast(sample_forecast(), sample_run(), "2026-09-10T120000Z")
    arsenal = document["teams"][0]
    assert arsenal["team_id"] == "arsenal"
    assert arsenal["name"] == "Arsenal"
    assert arsenal["events"] == {"relegation_probability": 0.0, "title_probability": 0.5}
    assert sum(arsenal["position_probabilities"]) == pytest.approx(1.0)
    assert "82" not in arsenal["points_distribution"]
    assert arsenal["points_quantiles_05_50_95"][2] == 97.0
    assert "score_probabilities" in document["matches"][0]


def test_distant_fixtures_stay_outside_the_horizon():
    document = derive_forecast(sample_forecast(), sample_run(), "2026-09-10T120000Z")
    assert [match["match_date"] for match in document["matches"]] == ["2026-09-12"]


def test_postponed_fixtures_are_disclosed_with_their_placement():
    from epl_forecast.live_forecast import UNSCHEDULED_PLACEHOLDER

    forecast = sample_forecast()
    match_id = "eng-premier-league:2026-2027:chelsea:arsenal-postponed"
    forecast["matches"].append(
        {
            **forecast["matches"][1],
            "match_id": match_id,
            "status": "unscheduled",
            "kickoff_time": None,
            "match_date": "2026-09-08",
            "model_forecast_date": "2026-09-10",
        }
    )
    forecast["unscheduled_fixtures"] = [match_id]
    forecast["unscheduled_placeholder"] = UNSCHEDULED_PLACEHOLDER
    document = derive_forecast(forecast, sample_run(), "2026-09-10T120000Z")
    check_publishable(document, load_policy())
    assert document["unscheduled_fixtures"] == [
        {
            "match_id": match_id,
            "home_team_id": "chelsea",
            "away_team_id": "arsenal",
            "match_date": "2026-09-08",
            "simulated_on": "2026-09-10",
        }
    ]
    assert document["unscheduled_assumption"] == UNSCHEDULED_PLACEHOLDER
    assert match_id not in {match["match_id"] for match in document["matches"]}
    plain = derive_forecast(sample_forecast(), sample_run(), "2026-09-10T120000Z")
    assert plain["unscheduled_fixtures"] == []
    assert plain["unscheduled_assumption"] is None


def test_a_thin_or_missing_projection_is_not_a_product():
    coarse = sample_forecast()
    coarse["simulation"]["simulations"] = 20
    with pytest.raises(ValueError, match="product floor"):
        derive_forecast(coarse, sample_run(), "2026-09-10T120000Z")
    without = sample_forecast()
    without["simulation"] = None
    with pytest.raises(ValueError, match="without a season projection"):
        derive_forecast(without, sample_run(), "2026-09-10T120000Z")


def test_check_publishable_refuses_private_content():
    policy = load_policy()
    with pytest.raises(ValueError, match="Private key"):
        check_publishable({"sources": []}, policy)
    with pytest.raises(ValueError, match="not on the publication allowlist"):
        check_publishable({"expected_goals": 1}, policy)
    with pytest.raises(ValueError, match="Private value"):
        check_publishable({"name": "/Users/someone/data"}, policy)
    with pytest.raises(ValueError, match="Unexpected digest"):
        check_publishable({"name": "d" * 64}, policy)


def test_publish_document_is_immutable_and_indexed(tmp_path):
    policy = load_policy()
    document = derive_forecast(sample_forecast(), sample_run(), "2026-09-10T120000Z")
    publish_document(tmp_path, document, policy)
    publish_document(tmp_path, document, policy)
    index = rebuild_index(tmp_path, policy)
    assert index["latest"] == "2026-09-10T120000Z"
    assert index["snapshots"][0]["competitions"][0]["href"] == (
        "forecasts/2026-09-10T120000Z/eng-premier-league.json"
    )
    with pytest.raises(ValueError, match="Refusing to overwrite"):
        publish_document(tmp_path, {**document, "simulations": 99}, policy)


def test_the_index_lists_divisions_in_pyramid_order(tmp_path):
    policy = load_policy()
    for competition in ("eng-league-two", "eng-championship", "eng-premier-league"):
        forecast = sample_forecast(competition)
        forecast["matches"] = []
        publish_document(
            tmp_path, derive_forecast(forecast, sample_run(), "2026-09-10T120000Z"), policy
        )
    index = rebuild_index(tmp_path, policy)
    assert [row["competition_id"] for row in index["snapshots"][0]["competitions"]] == [
        "eng-premier-league",
        "eng-championship",
        "eng-league-two",
    ]


class Store:
    def __init__(self):
        self.objects = {}

    def get_json(self, key, default=None):
        return self.objects.get(key, default)

    def put_json(self, key, value, immutable=False):
        if immutable and key in self.objects and self.objects[key] != value:
            raise ValueError(key)
        self.objects[key] = value

    def exists(self, key):
        return key in self.objects


def test_r2_index_advances_each_division_independently_and_materializes(tmp_path):
    store = Store()
    policy = load_policy()
    premier = derive_forecast(sample_forecast(), sample_run(), "2026-09-10T120000Z")
    championship_forecast = sample_forecast("eng-championship", "2026-09-11T12:00:00+00:00")
    championship = derive_forecast(championship_forecast, sample_run(), "2026-09-11T120000Z")
    later_premier = derive_forecast(
        sample_forecast(generated="2026-09-12T12:00:00+00:00"),
        sample_run(),
        "2026-09-12T120000Z",
    )
    publish_documents_to_store(store, [premier, championship], policy)
    index = publish_documents_to_store(store, [later_premier], policy)
    assert index["latest_by_competition"]["eng-premier-league"]["snapshot_id"] == (
        "2026-09-12T120000Z"
    )
    assert index["latest_by_competition"]["eng-championship"]["snapshot_id"] == (
        "2026-09-11T120000Z"
    )
    assert store.objects["hindcasts/index.json"]["namespace"] == "hindcasts"
    result = materialize_publication(store, tmp_path)
    assert result == {"documents": 3, "record": False}
    assert json.loads((tmp_path / "data/index.json").read_text()) == index
    assert json.loads((tmp_path / "data/hindcasts/index.json").read_text()) == empty_index(
        "hindcasts", store.objects["hindcasts/index.json"]["updated_at"]
    )
