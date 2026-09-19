from copy import deepcopy
from datetime import UTC, datetime

import duckdb
import pytest
from test_publication import sample_forecast, sample_run

from epl_forecast.market import market_assisted_probabilities
from epl_forecast.publication import derive_forecast
from epl_forecast.results import (
    clone_forecast_result,
    read_forecast_result,
    read_forecast_run,
    write_forecast_result,
)


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
            "market_assisted": None
            if match["market_assisted_probabilities"] is None
            else {
                "parent_stage": "personnel_adjusted",
                "score_generating": False,
                **match["market_assisted_probabilities"],
            },
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


def revision_context(moment):
    return {
        "generated_at": moment,
        "observed_at": moment,
        "software_provenance": {
            "execution": {"commit": "revision-commit"},
            "requested_cutoff": moment.isoformat(),
        },
    }


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
        "match_probabilities": 5,
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


def test_legacy_forecast_preserves_only_its_known_probability_stages(tmp_path):
    database = tmp_path / "results.duckdb"
    forecast = result_forecast()
    for match in forecast["matches"]:
        del match["stages"]
    write_forecast_result(
        database,
        forecast,
        sample_run(),
        input_revision="legacy-input",
        result_id="legacy-forecast",
    )

    restored = read_forecast_result(database, "legacy-forecast")
    for source, match in zip(forecast["matches"], restored["matches"], strict=True):
        assert match["stages"]["unadjusted"] is None
        assert match["stages"]["personnel_adjusted"]["p_home"] == source["p_home"]
        assert match["score_distribution"] == {
            **source["score_distribution"],
            "uncertainty_components": source["score_distribution"].get(
                "uncertainty_components", {}
            ),
        }
        expected_market = source["market_assisted_probabilities"]
        restored_market = match["market_assisted_probabilities"]
        if expected_market is None:
            assert restored_market is None
        else:
            assert {key: restored_market[key] for key in ("p_home", "p_draw", "p_away")} == {
                key: expected_market[key] for key in ("p_home", "p_draw", "p_away")
            }


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


def test_public_forecast_is_derived_from_typed_result(tmp_path):
    database = tmp_path / "results.duckdb"
    forecast = result_forecast()
    forecast["simulation"]["match_impacts"] = None
    write_forecast_result(
        database,
        forecast,
        sample_run(),
        input_revision="input-1",
        result_id="forecast-1",
    )
    restored = read_forecast_result(database, "forecast-1")
    assert derive_forecast(restored, "forecast-1") == derive_forecast(forecast, "forecast-1")


def test_display_refresh_reuses_all_forecast_values(tmp_path):
    database = tmp_path / "results.duckdb"
    write_forecast_result(
        database,
        result_forecast(),
        sample_run(),
        input_revision="input-1",
        result_id="forecast-1",
    )
    result = clone_forecast_result(
        database,
        "forecast-1",
        "forecast-2",
        **revision_context(datetime(2026, 9, 10, 13, tzinfo=UTC)),
        input_revision="input-2",
        team_names={"arsenal": "Arsenal FC", "chelsea": "Chelsea FC"},
    )
    assert result["status"] == "written"
    source = read_forecast_result(database, "forecast-1")
    refreshed = read_forecast_result(database, "forecast-2")
    assert refreshed["team_names"] == {
        "arsenal": "Arsenal FC",
        "chelsea": "Chelsea FC",
    }
    assert refreshed["matches"] == source["matches"]
    assert refreshed["simulation"] == source["simulation"]
    with duckdb.connect(str(database), read_only=True) as connection:
        for table in (
            "forecast_matches",
            "forecast_scores",
            "forecast_team_seasons",
            "forecast_team_events",
            "forecast_team_points",
            "forecast_team_positions",
            "forecast_team_strengths",
            "forecast_conditionals",
        ):
            assert connection.execute(
                f"SELECT count(*) FROM forecast_result.{table} WHERE result_id = 'forecast-2'"
            ).fetchone() == (0,)
    clone_forecast_result(
        database,
        "forecast-2",
        "forecast-3",
        **revision_context(datetime(2026, 9, 10, 14, tzinfo=UTC)),
        input_revision="input-3",
    )
    chained = read_forecast_result(database, "forecast-3")
    assert chained["team_names"] == refreshed["team_names"]
    assert chained["simulation"] == source["simulation"]
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute(
            "SELECT source_result_id FROM forecast_result.forecast_runs "
            "WHERE result_id = 'forecast-3'"
        ).fetchone() == ("forecast-1",)


def test_quote_refresh_replaces_only_market_probabilities(tmp_path):
    database = tmp_path / "results.duckdb"
    forecast = result_forecast()
    write_forecast_result(
        database,
        forecast,
        sample_run(),
        input_revision="input-1",
        result_id="forecast-1",
    )
    match_id = forecast["matches"][0]["match_id"]
    result = clone_forecast_result(
        database,
        "forecast-1",
        "forecast-2",
        **revision_context(datetime(2026, 9, 10, 13, tzinfo=UTC)),
        input_revision="input-2",
        replace_market=True,
        market_quotes=[
            {
                "match_id": match_id,
                "family": "closing",
                "home_odds": 1.6,
                "draw_odds": 4.0,
                "away_odds": 6.0,
                "retrieved_at": datetime(2026, 9, 10, 12, tzinfo=UTC),
            }
        ],
        market_pool={"market_family": "closing", "market_weight": 0.5},
    )
    assert result["status"] == "written"
    source = read_forecast_result(database, "forecast-1")
    refreshed = read_forecast_result(database, "forecast-2")
    source_match = next(row for row in source["matches"] if row["match_id"] == match_id)
    refreshed_match = next(row for row in refreshed["matches"] if row["match_id"] == match_id)
    assert (
        refreshed_match["market_assisted_probabilities"]
        != source_match["market_assisted_probabilities"]
    )
    assert refreshed_match["score_distribution"] == source_match["score_distribution"]
    assert refreshed["simulation"] == source["simulation"]
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute(
            "SELECT count(*) FROM forecast_result.forecast_match_probabilities "
            "WHERE result_id = 'forecast-2' AND stage = 'market_assisted'"
        ).fetchone() == (1,)


def test_market_revisions_are_complete_replacements_and_keep_one_level_lineage(tmp_path):
    database = tmp_path / "results.duckdb"
    forecast = result_forecast()
    pool = {"market_family": "closing", "market_weight": 0.5}

    def quote(match_id, home_odds, observed_at):
        return {
            "match_id": match_id,
            "family": "closing",
            "home_odds": home_odds,
            "draw_odds": 4.0,
            "away_odds": 6.0,
            "retrieved_at": observed_at,
            "source_sha256": f"quote-{home_odds}",
        }

    def equivalent_markets(quotes, market_pool):
        selected = {row["match_id"]: row for row in quotes}
        values = {}
        for match in forecast["matches"]:
            current = selected.get(match["match_id"])
            values[match["match_id"]] = (
                None
                if current is None or market_pool is None
                else market_assisted_probabilities(
                    (match["p_home"], match["p_draw"], match["p_away"]),
                    current,
                    market_pool,
                )
            )
        return values

    def restored_markets(result):
        return {
            row["match_id"]: (
                None
                if row["market_assisted_probabilities"] is None
                else {
                    key: value
                    for key, value in row["market_assisted_probabilities"].items()
                    if key not in {"parent_stage", "score_generating"}
                }
            )
            for row in result["matches"]
        }

    first_id, second_id = (row["match_id"] for row in forecast["matches"])
    original_second = quote(second_id, 2.1, datetime(2026, 9, 10, 10, tzinfo=UTC))
    second_values = equivalent_markets([original_second], pool)[second_id]
    forecast["matches"][1]["market_assisted_probabilities"] = second_values
    forecast["matches"][1]["stages"]["market_assisted"] = {
        "parent_stage": "personnel_adjusted",
        "score_generating": False,
        **second_values,
    }
    forecast["market_assistance"] = {
        **pool,
        "available_match_forecasts": 2,
        "season_simulation_uses_market": False,
    }
    write_forecast_result(
        database,
        forecast,
        sample_run(),
        input_revision="input-1",
        result_id="forecast-a",
    )

    updated = quote(first_id, 1.6, datetime(2026, 9, 10, 12, tzinfo=UTC))
    clone_forecast_result(
        database,
        "forecast-a",
        "forecast-b",
        **revision_context(datetime(2026, 9, 10, 13, tzinfo=UTC)),
        input_revision="input-2",
        replace_market=True,
        market_quotes=[updated],
        market_pool=pool,
    )
    result_b = read_forecast_result(database, "forecast-b")
    expected_b = equivalent_markets([updated], pool)
    assert restored_markets(result_b) == expected_b
    assert result_b["market_assistance"]["available_match_forecasts"] == 1
    assert result_b["state_observed_at"] == "2026-09-10T13:00:00+00:00"
    assert read_forecast_run(database, "forecast-b")["execution"]["commit"] == "revision-commit"

    clone_forecast_result(
        database,
        "forecast-b",
        "forecast-c",
        **revision_context(datetime(2026, 9, 10, 14, tzinfo=UTC)),
        input_revision="input-3",
        replace_market=True,
        market_quotes=[],
        market_pool=pool,
    )
    result_c = read_forecast_result(database, "forecast-c")
    assert restored_markets(result_c) == equivalent_markets([], pool)
    assert result_c["market_assistance"]["available_match_forecasts"] == 0

    clone_forecast_result(
        database,
        "forecast-b",
        "forecast-d",
        **revision_context(datetime(2026, 9, 10, 15, tzinfo=UTC)),
        input_revision="input-4",
        replace_market=True,
        market_quotes=[updated],
        market_pool=None,
    )
    result_d = read_forecast_result(database, "forecast-d")
    assert restored_markets(result_d) == equivalent_markets([updated], None)
    assert result_d["market_assistance"] is None

    clone_forecast_result(
        database,
        "forecast-d",
        "forecast-e",
        **revision_context(datetime(2026, 9, 10, 16, tzinfo=UTC)),
        input_revision="input-5",
        team_names={"arsenal": "Arsenal FC", "chelsea": "Chelsea FC"},
    )
    result_e = read_forecast_result(database, "forecast-e")
    assert restored_markets(result_e) == equivalent_markets([updated], None)
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute(
            "SELECT result_id, source_result_id, market_replacement "
            "FROM forecast_result.forecast_runs WHERE result_id != 'forecast-a' "
            "ORDER BY result_id"
        ).fetchall() == [
            ("forecast-b", "forecast-a", True),
            ("forecast-c", "forecast-a", True),
            ("forecast-d", "forecast-a", True),
            ("forecast-e", "forecast-a", True),
        ]


def test_result_clone_is_idempotent_and_cannot_name_different_content(tmp_path):
    database = tmp_path / "results.duckdb"
    write_forecast_result(
        database,
        result_forecast(),
        sample_run(),
        input_revision="input-1",
        result_id="forecast-1",
    )
    arguments = {
        **revision_context(datetime(2026, 9, 10, 13, tzinfo=UTC)),
        "input_revision": "input-2",
        "team_names": {"arsenal": "Arsenal FC", "chelsea": "Chelsea FC"},
    }
    clone_forecast_result(database, "forecast-1", "forecast-2", **arguments)
    assert (
        clone_forecast_result(database, "forecast-1", "forecast-2", **arguments)["status"]
        == "unchanged"
    )
    arguments["team_names"] = {"arsenal": "Arsenal", "chelsea": "Chelsea"}
    with pytest.raises(ValueError, match="different content"):
        clone_forecast_result(database, "forecast-1", "forecast-2", **arguments)
