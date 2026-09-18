from copy import deepcopy

import duckdb
import pytest
from test_publication import sample_forecast, sample_run

from epl_forecast.results import write_forecast_result


def result_forecast():
    forecast = sample_forecast("eng-championship")
    for match in forecast["matches"]:
        score = match["score_distribution"]
        match["stages"] = {
            "unadjusted": {
                "parent_stage": None,
                "score_generating": True,
                "p_home": match["p_home"],
                "p_draw": match["p_draw"],
                "p_away": match["p_away"],
                "score_distribution": {**score, "uncertainty_components": {}},
            },
            "personnel_adjusted": {
                "parent_stage": "unadjusted",
                "score_generating": True,
                "p_home": match["p_home"],
                "p_draw": match["p_draw"],
                "p_away": match["p_away"],
                "score_distribution": {**score, "uncertainty_components": {}},
            },
            "market_assisted": None,
        }
    forecast["team_strengths"] = [
        {
            "team_id": "arsenal",
            "quality": 0.4,
            "tilt": 0.1,
            "attack_log_rate": 0.5,
            "defense_log_rate": 0.3,
            "attack_sd": 0.2,
            "defense_sd": 0.2,
            "training_matches": 100,
            "state_source": "filtered state",
        }
    ]
    forecast["fit_diagnostics"] = {"updates": 100}
    forecast["simulation"]["match_impacts"] = {
        "fixtures": [
            {
                "match_id": forecast["matches"][0]["match_id"],
                "impacts": [
                    {
                        "team_id": "arsenal",
                        "event": "title_probability",
                        "baseline": 0.5,
                        "conditional": {"H": 0.6, "D": 0.5, "A": 0.4},
                        "standard_error": {"H": 0.01, "D": 0.01, "A": 0.01},
                        "rms_movement": 0.08,
                        "swing": 0.2,
                        "sufficient_sample": True,
                    }
                ],
            }
        ]
    }
    return forecast


def test_forecast_result_is_written_at_declared_grains(tmp_path):
    database = tmp_path / "results.duckdb"
    forecast = result_forecast()
    result = write_forecast_result(
        database,
        forecast,
        sample_run(),
        input_revision="input-1",
        result_id="forecast-1",
    )
    assert result == {
        "result_id": "forecast-1",
        "status": "written",
        "matches": 2,
        "match_probabilities": 4,
        "scores": 16,
        "teams": 2,
        "events": 4,
        "points": 5,
        "positions": 4,
        "strengths": 1,
        "conditionals": 3,
    }
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute(
            "SELECT competition_id, input_revision FROM forecast_result.forecast_runs"
        ).fetchall() == [("eng-championship", "input-1")]
        assert connection.execute(
            "SELECT event, round(avg(probability), 3) FROM forecast_result.forecast_team_events "
            "GROUP BY event ORDER BY event"
        ).fetchall() == [("relegation_probability", 0.0), ("title_probability", 0.5)]
        assert connection.execute(
            "SELECT count(*) FROM forecast_result.forecast_conditionals WHERE sufficient_sample"
        ).fetchone() == (3,)


def test_result_identity_is_idempotent_and_cannot_name_different_content(tmp_path):
    database = tmp_path / "results.duckdb"
    forecast = result_forecast()
    run = sample_run()
    write_forecast_result(database, forecast, run, input_revision="input-1", result_id="same")
    assert (
        write_forecast_result(database, forecast, run, input_revision="input-1", result_id="same")[
            "status"
        ]
        == "unchanged"
    )
    changed = deepcopy(forecast)
    changed["matches"][0]["stages"]["unadjusted"]["p_home"] = 0.4
    with pytest.raises(ValueError, match="different content"):
        write_forecast_result(database, changed, run, input_revision="input-1", result_id="same")


def test_invalid_probability_rolls_back_the_whole_result(tmp_path):
    database = tmp_path / "results.duckdb"
    forecast = result_forecast()
    forecast["matches"][0]["stages"]["unadjusted"]["p_home"] = 0.4
    with pytest.raises(ValueError, match="Invalid match probability"):
        write_forecast_result(
            database,
            forecast,
            sample_run(),
            input_revision="input-1",
            result_id="invalid",
        )
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute(
            "SELECT count(*) FROM forecast_result.forecast_runs"
        ).fetchone() == (0,)
