import json
import math

import duckdb
import pytest
from test_publication import sample_forecast, sample_run

from epl_forecast import analysis_contract
from epl_forecast.analysis import open_analysis_session, start_ui
from epl_forecast.datasets import publish
from epl_forecast.market import market_assisted_probabilities
from epl_forecast.publication import derive_forecast, forecast_pointer


class Store:
    def __init__(self, directory, manifests):
        self.directory = directory
        self.manifests = manifests

    def get_json(self, key, default=None):
        if key == "state/manifests.json":
            return {"schema_version": 1, "manifests": self.manifests}
        return default

    def uri(self, key):
        return str(self.directory / key)

    def configure_duckdb(self, connection, name="page324_r2"):
        pass


class ObjectStore:
    def __init__(self, objects=None):
        self.objects = objects or {}
        self.reads = []

    def get_json(self, key, default=None):
        self.reads.append(key)
        return self.objects.get(key, default)

    def uri(self, key):
        raise AssertionError(f"Unexpected Parquet read: {key}")

    def configure_duckdb(self, connection, name="page324_r2"):
        pass


def request(retrieved_at, source):
    return {
        "provider": "api_football",
        "retrieved_at": retrieved_at,
        "evidence_basis": "captured",
        "source_sha256": source * 64,
    }


def fixture(home_goals=2):
    return {
        "match_id": "eng-premier-league:2025-2026:arsenal:chelsea",
        "competition_id": "eng-premier-league",
        "season_id": "2025-2026",
        "stage": "regular",
        "home_team_id": "arsenal",
        "away_team_id": "chelsea",
        "match_date": "2026-01-01",
        "kickoff_time": "2026-01-01T15:00:00+00:00",
        "status": "finished",
        "home_goals": home_goals,
        "away_goals": 1,
    }


def test_analysis_matches_and_xg_are_the_product_selectors(tmp_path):
    remote = tmp_path / "remote"
    manifest = publish(
        remote,
        request("2026-01-02T12:00:00+00:00", "a"),
        {
            "fixtures": [fixture()],
            "team_statistics": [
                {
                    "match_id": fixture()["match_id"],
                    "team_id": team,
                    "competition_id": "eng-premier-league",
                    "season_id": "2025-2026",
                    "expected_goals": value,
                }
                for team, value in (("arsenal", 1.8), ("chelsea", 0.7))
            ],
        },
    )
    store = Store(remote, [manifest])
    session = open_analysis_session(data_store=store, include_derived=False)
    try:
        assert session.rows("SELECT * FROM analysis.matches") == session.dataset.fixtures()
        assert (
            session.rows("SELECT * FROM analysis.team_match_xg")
            == session.dataset.xg_observations()
        )
        assert session.rows("SELECT count(*) AS n FROM analysis.team_matches") == [{"n": 2}]
    finally:
        session.close()


def test_remote_only_session_ignores_local_manifests_and_post_cutoff_rows(tmp_path):
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    old = publish(
        remote,
        request("2026-01-02T12:00:00+00:00", "a"),
        {"fixtures": [fixture()]},
    )
    late = publish(
        remote,
        request("2026-01-04T12:00:00+00:00", "b"),
        {"fixtures": [fixture(home_goals=4)]},
    )
    local_manifest = publish(
        local,
        request("2026-01-02T13:00:00+00:00", "c"),
        {"fixtures": [fixture(home_goals=9)]},
    )
    assert json.loads((local / "manifests" / f"{local_manifest['batch_id']}.json").read_text())
    session = open_analysis_session(
        "2026-01-03T00:00:00+00:00",
        data_store=Store(remote, [old, late]),
        include_derived=False,
    )
    try:
        assert session.rows("SELECT home_goals FROM analysis.matches") == [{"home_goals": 2}]
        assert session.rows("SELECT remote_only FROM analysis.session") == [{"remote_only": True}]
    finally:
        session.close()


def test_personnel_views_keep_latest_successful_empty_snapshots(tmp_path):
    remote = tmp_path / "remote"
    old = publish(
        remote,
        request("2026-01-02T12:00:00+00:00", "a"),
        {
            "players": [{"player_id": "one", "name": "One"}],
            "memberships": [
                {
                    "player_id": "one",
                    "team_id": "arsenal",
                    "season_id": "2025-2026",
                    "competition_id": "eng-premier-league",
                    "basis": "captured_squad",
                    "scope": "1",
                }
            ],
            "source_snapshots": [
                {
                    "scope_kind": "team_squad",
                    "scope_key": "arsenal",
                    "endpoint": "players/squads",
                    "team_id": "arsenal",
                    "row_count": 1,
                }
            ],
        },
    )
    empty = publish(
        remote,
        request("2026-01-03T12:00:00+00:00", "b"),
        {
            "source_snapshots": [
                {
                    "scope_kind": "team_squad",
                    "scope_key": "arsenal",
                    "endpoint": "players/squads",
                    "team_id": "arsenal",
                    "row_count": 0,
                }
            ]
        },
    )
    session = open_analysis_session(data_store=Store(remote, [old, empty]), include_derived=False)
    try:
        assert session.rows(
            "SELECT team_id, row_count, player_id FROM analysis.squad_memberships"
        ) == [{"team_id": "arsenal", "row_count": 0, "player_id": None}]
    finally:
        session.close()

    historical = open_analysis_session(
        "2026-01-02T23:00:00+00:00",
        data_store=Store(remote, [old, empty]),
        include_derived=False,
    )
    try:
        assert historical.rows(
            "SELECT team_id, row_count, player_id FROM analysis.squad_memberships"
        ) == [{"team_id": "arsenal", "row_count": 1, "player_id": "one"}]
    finally:
        historical.close()


def forecast_stores():
    forecast_id = "2026-09-10T120000Z"
    private = {"schema_version": 1, **sample_forecast()}
    public = derive_forecast(private, forecast_id)
    pointer = forecast_pointer(public)
    archive = {
        "schema_version": 1,
        "competition_id": "eng-premier-league",
        "updated_at": "2026-09-10T12:01:00+00:00",
        "forecasts": [pointer],
    }
    data = ObjectStore(
        {
            "state/manifests.json": {"schema_version": 1, "manifests": []},
            f"runs/forecasts/{forecast_id}/eng-premier-league/forecast.json": private,
            f"runs/forecasts/{forecast_id}/eng-premier-league/run.json": sample_run(),
        }
    )
    publish_store = ObjectStore(
        {
            "forecasts/eng-premier-league/archive.json": archive,
            pointer["href"]: public,
            "record.json": {
                "schema_version": 2,
                "updated_at": "2026-09-10T12:02:00+00:00",
                "pending": [
                    {
                        "match_id": public["matches"][0]["match_id"],
                        "competition_id": public["competition_id"],
                        "season_id": public["season_id"],
                        "forecast_id": forecast_id,
                        "generated_at": public["generated_at"],
                        "kickoff_time": public["matches"][0]["kickoff_time"],
                        "model_version": public["model"]["version"],
                        "p_home": 0.5,
                        "p_draw": 0.25,
                        "p_away": 0.25,
                    }
                ],
                "settled": [],
                "summary": {"overall": {"scored": 0}},
            },
        }
    )
    return data, publish_store


def version_two_forecast_stores():
    data, publish_store = forecast_stores()
    forecast_id = "2026-09-10T120000Z"
    key = f"runs/forecasts/{forecast_id}/eng-premier-league/forecast.json"
    private = data.objects[key]
    private["schema_version"] = 2
    private["personnel"] = {
        "kappa": 0.4,
        "horizon_days": 6,
        "records": 1,
        "adjusted_fixtures": 1,
        "persistent_state_changed": False,
    }
    first = private["matches"][0]
    first["personnel"] = {
        "home_log_rate_shift": -0.08,
        "home": {
            "discontinuity": 0.3,
            "unresolved_weight": 0.2,
            "team_sheet_retrieved_at": None,
            "reference_matches": ["reference-home"],
            "players": [
                {
                    "player_id": "home-one",
                    "recent_weight": 0.4,
                    "membership": "member",
                    "membership_basis": ["captured squad"],
                    "membership_conflicts": [],
                    "recent_squads": 3,
                    "in_last_squad": True,
                    "availability": 1.0,
                    "availability_basis": ["no injury row"],
                    "probability": 0.5,
                },
                {
                    "player_id": "home-two",
                    "recent_weight": 0.2,
                    "membership": "member",
                    "membership_basis": ["matchday squad"],
                    "membership_conflicts": [],
                    "recent_squads": 2,
                    "in_last_squad": False,
                    "availability": 1.0,
                    "availability_basis": ["team sheet"],
                    "probability": 0.8,
                },
                {
                    "player_id": "home-unknown",
                    "recent_weight": 0.2,
                    "membership": "unknown",
                    "membership_basis": [],
                    "membership_conflicts": [],
                    "recent_squads": 1,
                    "in_last_squad": False,
                    "availability": None,
                    "availability_basis": [],
                    "probability": None,
                },
            ],
        },
        "away": {
            "discontinuity": 0.1,
            "unresolved_weight": 0.0,
            "team_sheet_retrieved_at": "2026-09-10T10:00:00+00:00",
            "reference_matches": ["reference-away"],
            "players": [
                {
                    "player_id": "away-one",
                    "recent_weight": 0.2,
                    "membership": "member",
                    "membership_basis": ["captured squad"],
                    "membership_conflicts": [],
                    "recent_squads": 3,
                    "in_last_squad": True,
                    "availability": 1.0,
                    "availability_basis": ["team sheet"],
                    "probability": 0.5,
                }
            ],
        },
    }
    unadjusted_score = {
        "home_rate": 1.6,
        "away_rate": 1.1,
        "omitted_probability": 0.0,
        "uncertainty_components": {"state": 0.2},
        "grid_home_rows_away_columns": [[0.25, 0.15], [0.25, 0.35]],
    }
    adjusted_score = {
        "home_rate": 1.6 * math.exp(-0.08),
        "away_rate": 1.1 * math.exp(0.08),
        "omitted_probability": 0.0,
        "uncertainty_components": {"state": 0.2},
        "grid_home_rows_away_columns": [[0.2, 0.2], [0.3, 0.3]],
    }
    quote = {
        "family": "closing",
        "retrieved_at": "2026-09-11T00:00:00+00:00",
        "home_odds": 2.0,
        "draw_odds": 3.5,
        "away_odds": 4.0,
    }
    assisted = market_assisted_probabilities((0.3, 0.5, 0.2), quote, {"market_weight": 0.25})
    first.update(
        {
            "p_home": 0.3,
            "p_draw": 0.5,
            "p_away": 0.2,
            "market_assisted_probabilities": assisted,
            "score_distribution": adjusted_score,
            "stages": {
                "unadjusted": {
                    "parent_stage": "model_state",
                    "score_generating": True,
                    "p_home": 0.25,
                    "p_draw": 0.6,
                    "p_away": 0.15,
                    "score_distribution": unadjusted_score,
                },
                "personnel_adjusted": {
                    "parent_stage": "unadjusted",
                    "score_generating": True,
                    "p_home": 0.3,
                    "p_draw": 0.5,
                    "p_away": 0.2,
                    "score_distribution": adjusted_score,
                },
                "market_assisted": {
                    "parent_stage": "personnel_adjusted",
                    "score_generating": False,
                    **assisted,
                },
            },
        }
    )
    second = private["matches"][1]
    neutral_score = {
        **second["score_distribution"],
        "grid_home_rows_away_columns": [[0.15, 0.3], [0.4, 0.15]],
    }
    neutral = {"p_home": 0.4, "p_draw": 0.3, "p_away": 0.3}
    second["stages"] = {
        "unadjusted": {
            "parent_stage": "model_state",
            "score_generating": True,
            **neutral,
            "score_distribution": neutral_score,
        },
        "personnel_adjusted": {
            "parent_stage": "unadjusted",
            "score_generating": True,
            **neutral,
            "score_distribution": neutral_score,
        },
        "market_assisted": None,
    }
    private["team_strengths"] = [
        {
            "team_id": "arsenal",
            "quality": 0.4,
            "tilt": 0.1,
            "quality_sd": 0.2,
            "tilt_sd": 0.3,
            "quality_tilt_covariance": 0.01,
            "quality_level": 0.35,
            "quality_form": 0.05,
            "quality_level_sd": 0.18,
            "quality_form_sd": 0.07,
            "quality_level_form_covariance": -0.002,
            "attack_log_rate": 0.5,
            "defense_log_rate": -0.2,
            "attack_sd": 0.25,
            "defense_sd": 0.3,
            "attack_multiplier": math.exp(0.5),
            "defense_multiplier": math.exp(-0.2),
            "training_matches": 20,
            "state_source": "posterior",
            "season_matches": 3,
        }
    ]
    private["fit_diagnostics"] = {
        "specifications": [
            {
                "quality_retention": 0.9,
                "quality_sd": 0.1,
                "form_retention": 0.3,
                "form_sd": 0.07,
                "tilt_retention": 0.8,
                "tilt_sd": 0.2,
                "dispersion": 20.0,
                "chance_probability": 0.05,
                "prior_weight": 0.5,
                "posterior_weight": 0.7,
                "log_evidence": -10.0,
            }
        ]
    }
    private["simulation"].update(
        {
            "seed": 7,
            "as_of": "2026-09-10",
            "played_matches": 3,
            "remaining_matches": 377,
            "state_uncertainty": "posterior",
            "future_state_evolution": True,
            "match_frequencies": [
                {"match_id": first["match_id"], "p_home": 0.31, "p_draw": 0.49, "p_away": 0.2}
            ],
        }
    )
    private["market_assistance"] = {
        "market_weight": 0.25,
        "available_match_forecasts": 1,
        "season_simulation_uses_market": False,
    }
    public = derive_forecast(private, forecast_id)
    public["impact"] = {
        "horizon_days": 7,
        "window_start": "2026-09-10T00:00:00+00:00",
        "window_end": "2026-09-17T11:00:00+00:00",
        "coverage": "every_team",
        "minimum_conditional_samples": 100,
        "fixtures": [
            {
                "match_id": first["match_id"],
                "match_date": first["match_date"],
                "kickoff_time": first["kickoff_time"],
                "home_team_id": first["home_team_id"],
                "away_team_id": first["away_team_id"],
                "status": "scheduled",
                "outcome": None,
                "outcome_counts": {"home": 3000, "draw": 4000, "away": 3000},
                "sufficient_sample": True,
                "max_standard_error": 0.01,
                "top_rms_movement": 0.1,
                "carried_from": None,
                "impacts": {
                    "title_probability": {
                        "team_id": ["arsenal"],
                        "home": [0.6],
                        "draw": [0.5],
                        "away": [0.4],
                        "rms_movement": [0.08],
                    }
                },
            }
        ],
    }
    pointer = publish_store.objects["forecasts/eng-premier-league/archive.json"]["forecasts"][0]
    publish_store.objects[pointer["href"]] = public
    return data, publish_store


def test_forecasts_follow_archive_pointers_and_keep_private_matches_distinct(tmp_path):
    data, publish_store = forecast_stores()
    data.objects["runs/forecasts/failed/eng-premier-league/forecast.json"] = {"schema_version": 1}
    session = open_analysis_session(data_store=data, publish_store=publish_store)
    try:
        assert session.rows("SELECT forecast_id FROM analysis.forecasts") == [
            {"forecast_id": "2026-09-10T120000Z"}
        ]
        matches = session.rows(
            "SELECT match_id, on_public_surface, structural_p_home, market_assisted_p_home "
            "FROM analysis.forecast_matches ORDER BY match_date"
        )
        assert [row["on_public_surface"] for row in matches] == [True, False]
        assert matches[0]["structural_p_home"] == 0.5
        assert matches[0]["market_assisted_p_home"] == 0.48
        assert matches[1]["market_assisted_p_home"] is None
        assert session.rows("SELECT count(*) AS n FROM analysis.forecast_teams") == [{"n": 2}]
        assert session.rows("SELECT record_state, outcome FROM analysis.record_matches") == [
            {"record_state": "pending", "outcome": None}
        ]
        assert not any("failed" in key for key in data.reads)
    finally:
        session.close()


def test_historical_stages_do_not_fabricate_discarded_unadjusted_probabilities(tmp_path):
    data, publish_store = forecast_stores()
    session = open_analysis_session(data_store=data, publish_store=publish_store)
    try:
        rows = session.rows(
            "SELECT match_id, stage, available, availability_reason, p_home "
            "FROM analysis.forecast_match_stages ORDER BY match_id, stage_order"
        )
        shifted = rows[:3]
        assert shifted[0]["stage"] == "unadjusted"
        assert shifted[0]["available"] is False
        assert "historical artifact" in shifted[0]["availability_reason"]
        assert shifted[0]["p_home"] is None
        assert shifted[1]["stage"] == "personnel_adjusted"
        assert shifted[1]["p_home"] == 0.5
        neutral = rows[3:]
        assert neutral[0]["p_home"] == neutral[1]["p_home"] == 0.4
    finally:
        session.close()


def test_team_usability_uses_only_the_evidence_of_that_team(tmp_path):
    data, publish_store = version_two_forecast_stores()
    private = data.objects["runs/forecasts/2026-09-10T120000Z/eng-premier-league/forecast.json"]
    second = private["matches"][1]
    second["personnel"] = {
        "home_log_rate_shift": None,
        "home": {"discontinuity": 0.2, "unresolved_weight": 0.5, "reference_matches": []},
        "away": {"discontinuity": 0.1, "unresolved_weight": 0.0, "reference_matches": []},
    }
    session = open_analysis_session(data_store=data, publish_store=publish_store)
    try:
        rows = session.rows(
            "SELECT side, usable_for_shift, status FROM analysis.forecast_personnel_teams "
            "WHERE match_id = ? ORDER BY side DESC",
            [second["match_id"]],
        )
    finally:
        session.close()
    assert rows == [
        {"side": "home", "usable_for_shift": False, "status": "unresolved_weight_too_high"},
        {"side": "away", "usable_for_shift": True, "status": "other_team_unusable"},
    ]


def test_new_forecast_stage_and_personnel_lineage_is_fully_queryable(tmp_path):
    data, publish_store = version_two_forecast_stores()
    session = open_analysis_session(data_store=data, publish_store=publish_store)
    try:
        comparison = session.rows(
            "SELECT * FROM analysis.forecast_match_stage_comparison WHERE personnel_applied"
        )[0]
        assert comparison["unadjusted_p_home"] == 0.25
        assert comparison["personnel_adjusted_p_home"] == 0.3
        assert comparison["D_home"] == 0.3
        assert comparison["D_away"] == 0.1
        assert comparison["home_log_rate_shift"] == pytest.approx(
            comparison["kappa"] * (comparison["D_away"] - comparison["D_home"])
        )

        contributions = session.rows(
            "SELECT team_id, sum(discontinuity_contribution) AS contribution "
            "FROM analysis.forecast_personnel_players "
            "WHERE discontinuity_contribution IS NOT NULL GROUP BY team_id ORDER BY team_id"
        )
        assert contributions == [
            {"team_id": "arsenal", "contribution": pytest.approx(0.3)},
            {"team_id": "chelsea", "contribution": pytest.approx(0.1)},
        ]
        unknown = session.rows(
            "SELECT expected_missing_weight, discontinuity_contribution "
            "FROM analysis.forecast_personnel_players WHERE player_id = 'home-unknown'"
        )[0]
        assert unknown == {"expected_missing_weight": None, "discontinuity_contribution": None}
        assert session.rows("SELECT count(*) AS n FROM analysis.forecast_personnel_evidence") == [
            {"n": 6}
        ]
        assert session.rows(
            "SELECT count(*) AS n FROM analysis.forecast_personnel_reference_matches"
        ) == [{"n": 2}]

        adjusted = session.rows(
            """
            SELECT sum(probability) FILTER (home_goals > away_goals) AS p_home,
                   sum(probability) FILTER (home_goals = away_goals) AS p_draw,
                   sum(probability) FILTER (home_goals < away_goals) AS p_away
            FROM analysis.forecast_score_grid
            WHERE stage = 'personnel_adjusted' AND match_id LIKE '%:arsenal:chelsea'
            """
        )[0]
        assert adjusted == {
            "p_home": pytest.approx(comparison["personnel_adjusted_p_home"]),
            "p_draw": pytest.approx(comparison["personnel_adjusted_p_draw"]),
            "p_away": pytest.approx(comparison["personnel_adjusted_p_away"]),
        }
        market = session.rows("SELECT * FROM analysis.forecast_market_inputs")[0]
        expected_market = market_assisted_probabilities(
            (0.3, 0.5, 0.2),
            {
                "family": market["market_family"],
                "retrieved_at": market["market_observed_at"],
                "home_odds": market["home_odds"],
                "draw_odds": market["draw_odds"],
                "away_odds": market["away_odds"],
            },
            {"market_weight": market["market_weight"]},
        )
        assert tuple(
            comparison[f"market_assisted_p_{side}"] for side in ("home", "draw", "away")
        ) == pytest.approx(tuple(expected_market[f"p_{side}"] for side in ("home", "draw", "away")))

        state = session.rows(
            "SELECT quality, tilt, quality_sd, tilt_sd, quality_tilt_covariance, quality_level, "
            "quality_form, quality_level_form_covariance, attack_sd, defense_sd, state_source, "
            "season_matches "
            "FROM analysis.model_team_states"
        )[0]
        assert state["tilt"] == 0.1
        assert (state["quality_level"], state["quality_form"]) == (0.35, 0.05)
        assert state["quality_level_form_covariance"] == -0.002
        assert state["state_source"] == "posterior"
        assert session.rows(
            "SELECT posterior_weight, chance_probability, form_retention "
            "FROM analysis.model_specifications"
        ) == [{"posterior_weight": 0.7, "chance_probability": 0.05, "form_retention": 0.3}]
        assert session.rows(
            "SELECT seed, state_uncertainty, future_state_evolution "
            "FROM analysis.forecast_simulation_runs"
        ) == [{"seed": 7, "state_uncertainty": "posterior", "future_state_evolution": True}]
        assert session.rows(
            "SELECT p_home, p_draw, p_away FROM analysis.forecast_simulation_match_frequencies"
        ) == [{"p_home": 0.31, "p_draw": 0.49, "p_away": 0.2}]
        assert session.rows(
            "SELECT outcome_count_home, sufficient_sample FROM analysis.forecast_impact_fixtures"
        ) == [{"outcome_count_home": 3000, "sufficient_sample": True}]
        assert session.rows(
            "SELECT DISTINCT baseline FROM analysis.forecast_impacts "
            "WHERE team_id = 'arsenal' AND event = 'title_probability'"
        ) == [{"baseline": 0.5}]
    finally:
        session.close()


def test_catalogs_cover_every_analysis_relation_and_column(tmp_path):
    data, publish_store = version_two_forecast_stores()
    session = open_analysis_session(data_store=data, publish_store=publish_store)
    try:
        assert (
            session.rows(
                """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'analysis'
            EXCEPT SELECT object_name FROM analysis.catalog
            """
            )
            == []
        )
        assert (
            session.rows(
                """
            SELECT table_name AS object_name, column_name
            FROM information_schema.columns WHERE table_schema = 'analysis'
            EXCEPT SELECT object_name, column_name FROM analysis.column_catalog
            """
            )
            == []
        )
    finally:
        session.close()


def test_a_successful_public_forecast_requires_its_private_run(tmp_path):
    data, publish_store = forecast_stores()
    del data.objects["runs/forecasts/2026-09-10T120000Z/eng-premier-league/forecast.json"]
    with pytest.raises(ValueError, match="pointer does not resolve"):
        open_analysis_session(data_store=data, publish_store=publish_store)


def test_hindcasts_are_pointer_driven_and_explicitly_retrospective(tmp_path):
    team = {
        "team_id": "arsenal",
        "name": "Arsenal",
        "played": 10,
        "current_points": 20,
        "mean_points": 75.0,
        "median_points": 75,
        "mean_position": 2.0,
        "median_position": 2,
        "position_sd": 1.0,
        "mean_goal_difference": 25.0,
        "points_intervals": {"50": [70, 80]},
        "position_intervals": {"50": [1, 3]},
        "points_distribution": {"74": 0.4, "75": 0.6},
        "position_probabilities": [0.3, 0.7],
        "events": {"title_probability": 0.2},
    }
    public = {
        "schema_version": 1,
        "product": "hindcast",
        "retrospective": True,
        "hindcast_id": "2025-10-01T080000Z",
        "competition_id": "eng-premier-league",
        "season_id": "2025-2026",
        "origin_at": "2025-10-01T09:00:00+01:00",
        "model_results_cutoff": "2025-10-01",
        "simulations": 10000,
        "played_matches": 50,
        "remaining_matches": 330,
        "model": {"version": "v0.2"},
        "teams": [team],
    }
    href = "hindcasts/v0.2/eng-premier-league/2025-2026/2025-10-01T080000Z.json"
    series_href = "hindcasts/v0.2/eng-premier-league/2025-2026/series.json"
    data = ObjectStore(
        {
            "state/manifests.json": {"schema_version": 1, "manifests": []},
            f"runs/{href}": {**public, "simulation": {"teams": [team]}},
        }
    )
    publish_store = ObjectStore(
        {
            "hindcasts/index.json": {
                "schema_version": 1,
                "retrospective": True,
                "updated_at": "2026-09-01T00:00:00+00:00",
                "seasons": [{"href": series_href}],
            },
            series_href: {
                "schema_version": 1,
                "retrospective": True,
                "origins": [{"href": href}],
            },
            href: public,
        }
    )
    session = open_analysis_session(data_store=data, publish_store=publish_store)
    try:
        origin = session.rows(
            "SELECT retrospective, generated_at, origin_at FROM analysis.hindcast_origins"
        )[0]
        assert origin["retrospective"] is True
        assert origin["generated_at"] is None
        assert str(origin["origin_at"]).startswith("2025-10-01 08:00:00")
        assert session.rows("SELECT count(*) AS n FROM analysis.hindcast_teams") == [{"n": 1}]
        assert session.rows("SELECT product, retrospective FROM analysis.team_projections") == [
            {"product": "hindcast", "retrospective": True}
        ]
    finally:
        session.close()


def test_ui_uses_the_prepared_connection_and_stops_cleanly(monkeypatch):
    statements = []

    class Result:
        def fetchone(self):
            return ("http://localhost:4213",)

    class Connection:
        def execute(self, sql):
            statements.append(sql)
            return Result()

    class Session:
        connection = Connection()

    def interrupt(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr("epl_forecast.analysis.time.sleep", interrupt)
    assert start_ui(Session(), open_browser=False) == "http://localhost:4213"
    assert statements == ["CALL start_ui_server()", "CALL stop_ui_server()"]


def test_session_file_is_reused_only_while_r2_state_is_unchanged(tmp_path, monkeypatch):
    data, publish_store = forecast_stores()
    directory = tmp_path / "sessions"
    first = open_analysis_session(
        data_store=data, publish_store=publish_store, session_directory=directory
    )
    try:
        assert first.rows("SELECT count(*) AS n FROM analysis.forecasts") == [{"n": 1}]
        with pytest.raises(duckdb.Error):
            first.connection.execute("CREATE TABLE analysis.local_note (value INTEGER)")
    finally:
        first.close()

    data.reads.clear()
    publish_store.reads.clear()
    second = open_analysis_session(
        data_store=data, publish_store=publish_store, session_directory=directory
    )
    second.close()
    assert second.path == first.path
    assert not any(key.endswith("/forecast.json") for key in data.reads)
    assert not any(key.endswith("T120000Z.json") for key in publish_store.reads)

    forecast_id = "2026-09-11T120000Z"
    private = {
        "schema_version": 1,
        **sample_forecast(generated="2026-09-11T12:00:00+00:00"),
    }
    public = derive_forecast(private, forecast_id)
    pointer = forecast_pointer(public)
    publish_store.objects[pointer["href"]] = public
    publish_store.objects["forecasts/eng-premier-league/archive.json"]["forecasts"].append(pointer)
    prefix = f"runs/forecasts/{forecast_id}/eng-premier-league"
    data.objects[f"{prefix}/forecast.json"] = private
    data.objects[f"{prefix}/run.json"] = sample_run()

    third = open_analysis_session(
        data_store=data, publish_store=publish_store, session_directory=directory
    )
    try:
        assert third.path != first.path
        assert third.rows("SELECT count(*) AS n FROM analysis.forecasts") == [{"n": 2}]
    finally:
        third.close()
    assert sorted(directory.iterdir()) == [third.path]

    monkeypatch.setattr(
        analysis_contract,
        "ANALYSIS_SCHEMA_VERSION",
        analysis_contract.ANALYSIS_SCHEMA_VERSION + 1,
    )
    rebuilt = open_analysis_session(
        data_store=data, publish_store=publish_store, session_directory=directory
    )
    rebuilt.close()
    assert rebuilt.path != third.path
    assert sorted(directory.iterdir()) == [rebuilt.path]


def test_session_files_are_separate_for_each_cutoff(tmp_path):
    remote = tmp_path / "remote"
    old = publish(remote, request("2026-01-02T12:00:00+00:00", "a"), {"fixtures": [fixture()]})
    late = publish(
        remote,
        request("2026-01-04T12:00:00+00:00", "b"),
        {"fixtures": [fixture(home_goals=4)]},
    )
    store = Store(remote, [old, late])
    directory = tmp_path / "sessions"
    goals = "SELECT home_goals FROM analysis.matches"
    current = open_analysis_session(
        data_store=store, include_derived=False, session_directory=directory
    )
    historical = open_analysis_session(
        "2026-01-03T00:00:00+00:00",
        data_store=store,
        include_derived=False,
        session_directory=directory,
    )
    try:
        assert current.rows(goals) == [{"home_goals": 4}]
        assert historical.rows(goals) == [{"home_goals": 2}]
        assert sorted(directory.iterdir()) == sorted([current.path, historical.path])
    finally:
        current.close()
        historical.close()
