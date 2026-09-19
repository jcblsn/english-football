import json

import pytest

from epl_forecast.publication import (
    activate_publication,
    activated_documents,
    check_publishable,
    deployment_pending,
    derive_forecast,
    empty_archive,
    empty_current,
    load_policy,
    materialize_publication,
    publish_documents,
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
        "model": {"id": "M10-xg-v1", "kind": "bayesian_xg_quality_tilt", "parameters": {}},
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
                "personnel": {
                    "home": {"discontinuity": 0.1},
                    "away": {"discontinuity": 0.3},
                    "home_log_rate_shift": 0.08632315756316625,
                },
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
                "personnel": None,
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


def test_document_contracts_respect_the_boundary():
    assert load_policy()["product"]["model_version"] == "v0.3.0"


def test_derived_forecast_drops_provider_evidence():
    document = derive_forecast(sample_forecast(), "2026-09-10T120000Z")
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
    assert document["matches"][0]["personnel"] == {
        "home_discontinuity": 0.1,
        "away_discontinuity": 0.3,
        "home_log_rate_shift": 0.086323,
    }
    assert "M10" not in text
    assert "code_sha256" not in text
    assert "verification" not in text


def test_derived_forecast_keeps_the_distributional_surface():
    document = derive_forecast(sample_forecast(), "2026-09-10T120000Z")
    arsenal = document["teams"][0]
    assert arsenal["team_id"] == "arsenal"
    assert arsenal["name"] == "Arsenal"
    assert arsenal["events"] == {"relegation_probability": 0.0, "title_probability": 0.5}
    assert sum(arsenal["position_probabilities"]) == pytest.approx(1.0)
    assert "82" not in arsenal["points_distribution"]
    assert arsenal["points_quantiles_05_50_95"][2] == 97.0
    assert "score_probabilities" in document["matches"][0]


def test_distant_fixtures_stay_outside_the_horizon():
    document = derive_forecast(sample_forecast(), "2026-09-10T120000Z")
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
    document = derive_forecast(forecast, "2026-09-10T120000Z")
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
    plain = derive_forecast(sample_forecast(), "2026-09-10T120000Z")
    assert plain["unscheduled_fixtures"] == []
    assert plain["unscheduled_assumption"] is None


def test_a_thin_or_missing_projection_is_not_a_product():
    coarse = sample_forecast()
    coarse["simulation"]["simulations"] = 20
    with pytest.raises(ValueError, match="product floor"):
        derive_forecast(coarse, "2026-09-10T120000Z")
    without = sample_forecast()
    without["simulation"] = None
    with pytest.raises(ValueError, match="without a season projection"):
        derive_forecast(without, "2026-09-10T120000Z")


def test_check_publishable_refuses_private_content():
    policy = load_policy()
    with pytest.raises(ValueError, match="Private key"):
        check_publishable({"sources": []}, policy, "forecast")
    with pytest.raises(ValueError, match="not in the forecast contract"):
        check_publishable({"expected_goals": 1}, policy, "forecast")
    with pytest.raises(ValueError, match="Private value"):
        check_publishable({"name": "/Users/someone/data"}, policy, "forecast")
    with pytest.raises(ValueError, match="Unexpected digest"):
        check_publishable({"name": "d" * 64}, policy, "forecast")


class Store:
    def __init__(self):
        self.objects = {}
        self.versions = {}
        self.writes = []
        self.reads = []

    def get_json(self, key, default=None):
        self.reads.append(key)
        return self.objects.get(key, default)

    def put_json(self, key, value, immutable=False):
        if immutable and key in self.objects and self.objects[key] != value:
            raise ValueError(key)
        self.objects[key] = value
        self.versions[key] = str(int(self.versions.get(key, "0")) + 1)
        self.writes.append((key, immutable))

    def get_json_versioned(self, key, default=None):
        return self.objects.get(key, default), self.versions.get(key)

    def put_json_if(self, key, value, version):
        assert self.versions.get(key) == version
        self.put_json(key, value)

    def exists(self, key):
        return key in self.objects


def test_current_advances_each_division_independently_and_materializes_only_current(tmp_path):
    store = Store()
    policy = load_policy()
    premier = derive_forecast(sample_forecast(), "2026-09-10T120000Z")
    championship_forecast = sample_forecast("eng-championship", "2026-09-11T12:00:00+00:00")
    championship = derive_forecast(championship_forecast, "2026-09-11T120000Z")
    later_premier = derive_forecast(
        sample_forecast(generated="2026-09-12T12:00:00+00:00"),
        "2026-09-12T120000Z",
    )
    publish_documents(store, [premier, championship], policy)
    current = publish_documents(store, [later_premier], policy)
    latest = {row["competition_id"]: row for row in current["forecasts"]}
    assert latest["eng-premier-league"]["forecast_id"] == "2026-09-12T120000Z"
    assert latest["eng-championship"]["forecast_id"] == "2026-09-11T120000Z"
    stale = tmp_path / "data/forecasts/old.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("stale")
    result = materialize_publication(store, tmp_path)
    assert result == {"documents": 2, "archives": 0, "hindcasts": 0, "record": False}
    assert json.loads((tmp_path / "data/current.json").read_text()) == current
    assert not stale.exists()
    assert not (tmp_path / "data/forecasts/eng-premier-league/archive.json").exists()

    archived = materialize_publication(store, tmp_path, ("eng-premier-league",))
    assert archived == {"documents": 3, "archives": 1, "hindcasts": 0, "record": False}
    archive = json.loads((tmp_path / "data/forecasts/eng-premier-league/archive.json").read_text())
    assert archive == store.objects["forecasts/eng-premier-league/archive.json"]
    assert [row["forecast_id"] for row in archive["forecasts"]] == [
        "2026-09-12T120000Z",
        "2026-09-10T120000Z",
    ]


def test_immutable_forecasts_and_archive_are_written_before_current_pointer():
    store = Store()
    document = derive_forecast(sample_forecast(), "2026-09-10T120000Z")

    publish_documents(store, [document], load_policy())

    assert store.writes[:4] == [
        ("forecasts/eng-premier-league/2026-09-10T120000Z.json", True),
        ("commitments/eng-premier-league/2026-09-10T120000Z.json", True),
        ("forecasts/eng-premier-league/archive.json", False),
        ("forecasts/current.json", False),
    ]
    assert store.writes[4][0].startswith("deployments/revisions/")
    assert store.writes[4][1]
    assert store.writes[5] == ("deployments/desired.json", False)
    assert empty_current("now") == {
        "schema_version": 1,
        "updated_at": "now",
        "forecasts": [],
    }
    assert empty_archive("eng-league-one", "now")["competition_id"] == "eng-league-one"


def test_public_activation_is_separate_from_private_commitment():
    store = Store()
    document = derive_forecast(sample_forecast(), "2026-09-10T120000Z")
    publish_documents(store, [document], load_policy())
    revision_id = store.objects["deployments/desired.json"]["revision_id"]

    assert deployment_pending(store)
    assert activated_documents(store) == []

    activation = activate_publication(store, revision_id)

    assert not deployment_pending(store)
    activated = activated_documents(store)
    assert [row["forecast_id"] for row in activated] == ["2026-09-10T120000Z"]
    assert activated[0]["released_at"] == activation["activated_at"]


def test_repeated_revision_keeps_the_first_forecast_activation():
    store = Store()
    first = derive_forecast(sample_forecast(), "2026-09-10T120000Z")
    publish_documents(store, [first], load_policy())
    first_revision = store.objects["deployments/desired.json"]["revision_id"]
    activate_publication(store, first_revision)
    first_receipt = store.objects["availability/eng-premier-league/2026-09-10T120000Z.json"]

    second = derive_forecast(
        sample_forecast("eng-championship", "2026-09-11T12:00:00+00:00"),
        "2026-09-11T120000Z",
    )
    publish_documents(store, [second], load_policy())
    second_revision = store.objects["deployments/desired.json"]["revision_id"]
    activate_publication(store, second_revision)

    assert store.objects["availability/eng-premier-league/2026-09-10T120000Z.json"] == first_receipt
