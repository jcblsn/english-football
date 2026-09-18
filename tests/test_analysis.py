import json
import math
from datetime import date, datetime

import duckdb
import pytest
from test_publication import sample_forecast, sample_run

from epl_forecast import analysis_contract
from epl_forecast.analysis import (
    ALL_MODEL_VERSIONS,
    CURRENT_MODEL_VERSION,
    open_analysis_session,
    start_ui,
)
from epl_forecast.datasets import publish
from epl_forecast.market import market_assisted_probabilities
from epl_forecast.publication import derive_forecast, forecast_pointer
from epl_forecast.results import (
    expire_forecast_detail,
    store_public_projection,
    write_forecast_result,
)
from epl_forecast.storage import file_hash, json_bytes, sha256_bytes


def identity(value):
    """The compact change token of a mutable pointer, as `R2Store.identities` returns it."""
    return None if value is None else sha256_bytes(json_bytes(value))


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

    def identities(self, keys):
        return {key: identity(self.get_json(key)) for key in keys}

    def configure_duckdb(self, connection, name="page324_r2"):
        pass


class ObjectStore:
    def __init__(self, objects=None):
        self.objects = objects or {}
        self.reads = []

    def get_json(self, key, default=None):
        self.reads.append(key)
        return self.objects.get(key, default)

    def identities(self, keys):
        return {key: identity(self.objects.get(key)) for key in keys}

    def download(self, key, destination):
        self.reads.append(key)
        destination.write_bytes(self.objects[key])

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


def test_typed_result_analysis_avoids_per_forecast_remote_reads(tmp_path):
    data, publish_store = version_two_forecast_stores()
    forecast_id = "2026-09-10T120000Z"
    private_key = f"runs/forecasts/{forecast_id}/eng-premier-league/forecast.json"
    database = tmp_path / "results.duckdb"
    write_forecast_result(
        database,
        data.objects[private_key],
        data.objects[f"runs/forecasts/{forecast_id}/eng-premier-league/run.json"],
        input_revision="input-1",
        result_id=forecast_id,
    )
    unrelated_id = "2026-09-10T130000Z"
    write_forecast_result(
        database,
        data.objects[private_key],
        data.objects[f"runs/forecasts/{forecast_id}/eng-premier-league/run.json"],
        input_revision="input-1",
        result_id=unrelated_id,
    )
    unrelated = derive_forecast(data.objects[private_key], unrelated_id)
    unrelated_pointer = forecast_pointer(unrelated)
    publish_store.objects["forecasts/eng-premier-league/archive.json"]["forecasts"].append(
        unrelated_pointer
    )
    publish_store.objects[unrelated_pointer["href"]] = unrelated
    for index in range(250):
        retained_id = f"retained-{index:03d}"
        publish_store.objects["forecasts/eng-premier-league/archive.json"]["forecasts"].append(
            {
                **unrelated_pointer,
                "forecast_id": retained_id,
                "href": f"forecasts/eng-premier-league/{retained_id}.json",
            }
        )
    database_key = "results/eng-premier-league/result.duckdb"
    data.objects[database_key] = database.read_bytes()
    data.objects["state/results/eng-premier-league.json"] = {
        "schema_version": 1,
        "competition_id": "eng-premier-league",
        "database_key": database_key,
        "database_bytes": database.stat().st_size,
        "database_sha256": file_hash(database),
    }
    data.reads.clear()
    publish_store.reads.clear()
    session = open_analysis_session(
        data_store=data,
        publish_store=publish_store,
        forecast_ids=[forecast_id],
    )
    try:
        assert session.rows("SELECT count(*) AS n FROM analysis.forecasts") == [{"n": 1}]
        assert session.rows("SELECT count(*) AS n FROM analysis.forecast_personnel_players") == [
            {"n": 4}
        ]
        assert session.rows(
            "SELECT home_odds, market_weight FROM analysis.forecast_market_inputs"
        ) == [{"home_odds": 2.0, "market_weight": 0.25}]
        assert session.rows(
            "SELECT count(*) AS n FROM analysis.forecast_simulation_match_frequencies"
        ) == [{"n": 1}]
        assert session.rows("SELECT forecast_ids FROM analysis.session") == [
            {"forecast_ids": json.dumps([forecast_id])}
        ]
    finally:
        session.close()
    public_href = publish_store.objects["forecasts/eng-premier-league/archive.json"]["forecasts"][
        0
    ]["href"]
    assert database_key in data.reads
    assert private_key not in data.reads
    assert public_href not in publish_store.reads


def test_expired_private_detail_keeps_public_history_in_the_typed_store(tmp_path):
    data, publish_store = version_two_forecast_stores()
    forecast_id = "2026-09-10T120000Z"
    prefix = f"runs/forecasts/{forecast_id}/eng-premier-league"
    private = data.objects[f"{prefix}/forecast.json"]
    database = tmp_path / "results.duckdb"
    write_forecast_result(
        database,
        private,
        data.objects[f"{prefix}/run.json"],
        input_revision="input-1",
        result_id=forecast_id,
    )
    public = derive_forecast(private, forecast_id)
    store_public_projection(database, forecast_id, public)
    expire_forecast_detail(database, datetime.fromisoformat("2026-09-11T00:00:00+00:00"))
    database_key = "results/eng-premier-league/result.duckdb"
    data.objects[database_key] = database.read_bytes()
    data.objects["state/results/eng-premier-league.json"] = {
        "schema_version": 1,
        "competition_id": "eng-premier-league",
        "database_key": database_key,
        "database_bytes": database.stat().st_size,
        "database_sha256": file_hash(database),
    }
    data.reads.clear()
    publish_store.reads.clear()
    session = open_analysis_session(
        data_store=data,
        publish_store=publish_store,
        forecast_ids=[forecast_id],
    )
    try:
        assert session.rows("SELECT count(*) AS n FROM analysis.forecasts") == [{"n": 1}]
        assert session.rows("SELECT count(*) AS n FROM analysis.forecast_teams") == [{"n": 2}]
        assert session.rows("SELECT private_schema_version FROM analysis.forecasts") == [
            {"private_schema_version": 1}
        ]
    finally:
        session.close()
    href = publish_store.objects["forecasts/eng-premier-league/archive.json"]["forecasts"][0][
        "href"
    ]
    assert database_key in data.reads
    assert href not in publish_store.reads


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
                "seasons": [{"model_version": "v0.2", "href": series_href}],
            },
            series_href: {
                "schema_version": 1,
                "retrospective": True,
                "origins": [{"href": href}],
            },
            href: public,
        }
    )
    session = open_analysis_session(
        data_store=data, publish_store=publish_store, hindcast_versions=ALL_MODEL_VERSIONS
    )
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


def test_the_hindcast_archive_keeps_every_published_model_version(tmp_path):
    """The archive indexes each model version, so one origin recurs under several versions."""
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

    def documents(version, mean_points):
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
            "model": {"version": version},
            "teams": [{**team, "mean_points": mean_points}],
        }
        prefix = f"hindcasts/{version}/eng-premier-league/2025-2026"
        return public, f"{prefix}/2025-10-01T080000Z.json", f"{prefix}/series.json"

    older, older_href, older_series = documents("v0.2", 75.0)
    newer, newer_href, newer_series = documents("v0.3.0", 78.0)
    data = ObjectStore(
        {
            "state/manifests.json": {"schema_version": 1, "manifests": []},
            f"runs/{older_href}": {**older, "simulation": {"teams": [team]}},
            f"runs/{newer_href}": {**newer, "simulation": {"teams": [team]}},
        }
    )
    publish_store = ObjectStore(
        {
            "hindcasts/index.json": {
                "schema_version": 1,
                "retrospective": True,
                "updated_at": "2026-09-17T00:00:00+00:00",
                "seasons": [
                    {"model_version": "v0.2", "href": older_series},
                    {"model_version": "v0.3.0", "href": newer_series},
                ],
            },
            older_series: {
                "schema_version": 1,
                "retrospective": True,
                "origins": [{"href": older_href}],
            },
            newer_series: {
                "schema_version": 1,
                "retrospective": True,
                "origins": [{"href": newer_href}],
            },
            older_href: older,
            newer_href: newer,
        }
    )
    session = open_analysis_session(
        data_store=data, publish_store=publish_store, hindcast_versions=ALL_MODEL_VERSIONS
    )
    try:
        assert session.rows(
            "SELECT model_version FROM analysis.hindcast_origins ORDER BY model_version"
        ) == [{"model_version": "v0.2"}, {"model_version": "v0.3.0"}]
        assert session.rows(
            "SELECT model_version, mean_points FROM analysis.hindcast_teams ORDER BY model_version"
        ) == [
            {"model_version": "v0.2", "mean_points": 75.0},
            {"model_version": "v0.3.0", "mean_points": 78.0},
        ]
        assert session.rows(
            "SELECT model_version, mean_points FROM analysis.team_projections ORDER BY model_version"
        ) == [
            {"model_version": "v0.2", "mean_points": 75.0},
            {"model_version": "v0.3.0", "mean_points": 78.0},
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


def hindcast_archive_stores(current_version="v0.3.0"):
    """Two hindcast generations of one season, with a live forecast that names the current one."""
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
    data_objects = {"state/manifests.json": {"schema_version": 1, "manifests": []}}
    publish_objects = {}
    seasons = []
    for version in ("v0.2", "v0.3.0"):
        prefix = f"hindcasts/{version}/eng-premier-league/2025-2026"
        href = f"{prefix}/2025-10-01T080000Z.json"
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
            "model": {"version": version},
            "teams": [team],
        }
        data_objects[f"runs/{href}"] = {**public, "simulation": {"teams": [team]}}
        publish_objects[href] = public
        publish_objects[f"{prefix}/series.json"] = {
            "schema_version": 1,
            "retrospective": True,
            "origins": [{"href": href}],
        }
        seasons.append({"model_version": version, "href": f"{prefix}/series.json"})
    publish_objects["hindcasts/index.json"] = {
        "schema_version": 1,
        "retrospective": True,
        "updated_at": "2026-09-17T00:00:00+00:00",
        "seasons": seasons,
    }
    publish_objects["forecasts/current.json"] = {
        "schema_version": 1,
        "updated_at": "2026-09-17T15:00:00+00:00",
        "forecasts": [
            {
                "competition_id": "eng-premier-league",
                "competition_name": "Premier League",
                "season_id": "2026-2027",
                "forecast_id": "2026-09-17T144601Z",
                "generated_at": "2026-09-17T14:56:47+00:00",
                "model_version": current_version,
                "matches": 10,
                "href": "forecasts/eng-premier-league/2026-09-17T144601Z.json",
            }
        ],
    }
    return ObjectStore(data_objects), ObjectStore(publish_objects)


def loaded_hindcast_versions(**kwargs):
    data, publish_store = hindcast_archive_stores()
    session = open_analysis_session(data_store=data, publish_store=publish_store, **kwargs)
    try:
        return (
            [
                row["model_version"]
                for row in session.rows(
                    "SELECT DISTINCT model_version FROM analysis.hindcast_origins "
                    "ORDER BY model_version"
                )
            ],
            session.rows(
                "SELECT hindcast_version_request, hindcast_model_versions FROM analysis.session"
            )[0],
            publish_store.reads,
        )
    finally:
        session.close()


def test_the_default_session_loads_only_the_current_model_version():
    versions, session_row, reads = loaded_hindcast_versions()
    assert versions == ["v0.3.0"]
    assert session_row["hindcast_version_request"] == CURRENT_MODEL_VERSION
    assert json.loads(session_row["hindcast_model_versions"]) == ["v0.3.0"]
    # The superseded generation is filtered in the index, before its series or its origins.
    assert not any("/v0.2/" in key for key in reads)


def test_an_older_or_every_hindcast_version_stays_available():
    assert loaded_hindcast_versions(hindcast_versions="v0.2")[0] == ["v0.2"]
    assert loaded_hindcast_versions(hindcast_versions=("v0.2", "v0.3.0"))[0] == ["v0.2", "v0.3.0"]
    every, session_row, _ = loaded_hindcast_versions(hindcast_versions=ALL_MODEL_VERSIONS)
    assert every == ["v0.2", "v0.3.0"]
    assert session_row["hindcast_version_request"] == ALL_MODEL_VERSIONS


def test_a_version_selection_must_name_a_version():
    data, publish_store = hindcast_archive_stores()
    with pytest.raises(ValueError, match="distinct, nonempty model version names"):
        open_analysis_session(data_store=data, publish_store=publish_store, hindcast_versions=())


def test_each_version_selection_keeps_its_own_session_file(tmp_path):
    data, publish_store = hindcast_archive_stores()
    directory = tmp_path / "sessions"
    current = open_analysis_session(
        data_store=data, publish_store=publish_store, session_directory=directory
    )
    every = open_analysis_session(
        data_store=data,
        publish_store=publish_store,
        session_directory=directory,
        hindcast_versions=ALL_MODEL_VERSIONS,
    )
    try:
        assert current.path != every.path
        assert sorted(directory.iterdir()) == sorted([current.path, every.path])
    finally:
        current.close()
        every.close()


def test_a_warm_session_checks_pointer_identities_without_reading_them(tmp_path):
    data, publish_store = forecast_stores()
    directory = tmp_path / "sessions"
    first = open_analysis_session(
        data_store=data, publish_store=publish_store, session_directory=directory
    )
    first.close()

    data.reads.clear()
    publish_store.reads.clear()
    second = open_analysis_session(
        data_store=data, publish_store=publish_store, session_directory=directory
    )
    second.close()
    assert second.path == first.path
    assert data.reads == [] and publish_store.reads == []

    publish_store.objects["record.json"]["updated_at"] = "2026-09-11T00:00:00+00:00"
    third = open_analysis_session(
        data_store=data, publish_store=publish_store, session_directory=directory
    )
    third.close()
    assert third.path != first.path


def test_a_new_hindcast_origin_changes_the_index_and_the_session_identity(tmp_path):
    """The index is the transitive identity of the series it selects, so nothing reads a series."""
    data, publish_store = hindcast_archive_stores()
    directory = tmp_path / "sessions"
    first = open_analysis_session(
        data_store=data,
        publish_store=publish_store,
        session_directory=directory,
        hindcast_versions=ALL_MODEL_VERSIONS,
    )
    first.close()
    index = publish_store.objects["hindcasts/index.json"]
    index["seasons"][1] = {**index["seasons"][1], "origin_count": 2}
    index["updated_at"] = "2026-09-18T00:00:00+00:00"
    second = open_analysis_session(
        data_store=data,
        publish_store=publish_store,
        session_directory=directory,
        hindcast_versions=ALL_MODEL_VERSIONS,
    )
    second.close()
    assert second.path != first.path


MATCH_HINDCAST_HREF = "match-hindcasts/v0.3.0/eng-premier-league/2026-2027/aaaa1111.json"


def match_hindcast_document(match_id, match_date="2026-08-15", model_version="v0.3.0"):
    return {
        "schema_version": 1,
        "product": "match_hindcast",
        "retrospective": True,
        "competition_id": "eng-premier-league",
        "competition_name": "Premier League",
        "season_id": "2026-2027",
        "model": {"version": model_version},
        "prospective_from": "2026-09-17",
        "last_match_date": match_date,
        "deferred_fixtures": [],
        "matches": [
            {
                "match_id": match_id,
                "match_date": match_date,
                "kickoff_time": f"{match_date}T14:00:00+00:00",
                "home_team_id": "arsenal",
                "away_team_id": "chelsea",
                "origin_at": f"{match_date}T00:00:00+01:00",
                "model_results_cutoff": match_date,
                "p_home": 0.5,
                "p_draw": 0.25,
                "p_away": 0.25,
                "unadjusted": {"p_home": 0.52, "p_draw": 0.24, "p_away": 0.24},
                "personnel": {
                    "home_discontinuity": 0.1,
                    "away_discontinuity": 0.3,
                    "home_log_rate_shift": -0.08,
                },
                "score_probabilities": {
                    "home_rate": 1.6,
                    "away_rate": 1.2,
                    "omitted_probability": 0.2,
                    # 0-0 and 1-1 draw, 0-1 away, 1-0 home. The retained cells give 0.4/0.2/0.2
                    # against a published 0.5/0.25/0.25; the missing 0.2 is the omitted tail.
                    "grid_home_rows_away_columns": [[0.2, 0.2], [0.4, 0.0]],
                },
            }
        ],
    }


def match_hindcast_stores(match_id, match_date="2026-08-15"):
    data, publish_store = hindcast_archive_stores()
    publish_store.objects[MATCH_HINDCAST_HREF] = match_hindcast_document(match_id, match_date)
    publish_store.objects["match-hindcasts/index.json"] = {
        "schema_version": 1,
        "product": "match_hindcast",
        "retrospective": True,
        "updated_at": "2026-09-18T00:00:00+00:00",
        "seasons": [{"model_version": "v0.3.0", "href": MATCH_HINDCAST_HREF}],
    }
    return data, publish_store


def test_match_hindcasts_carry_retrospective_timing_and_the_realized_result(tmp_path):
    remote = tmp_path / "remote"
    manifest = publish(
        remote,
        request("2026-08-16T12:00:00+00:00", "a"),
        {
            "fixtures": [
                {
                    **fixture(),
                    "match_id": "eng-premier-league:2026-2027:arsenal:chelsea",
                    "season_id": "2026-2027",
                    "match_date": "2026-08-15",
                    "kickoff_time": "2026-08-15T14:00:00+00:00",
                }
            ]
        },
    )
    match_id = "eng-premier-league:2026-2027:arsenal:chelsea"
    data, publish_store = match_hindcast_stores(match_id)
    data.objects["state/manifests.json"] = {"schema_version": 1, "manifests": [manifest]}
    data.uri = lambda key: str(remote / key)
    session = open_analysis_session(data_store=data, publish_store=publish_store)
    try:
        assert session.rows(
            "SELECT model_version, match_id, retrospective, origin_at, model_results_cutoff, "
            "prospective_from, personnel_applied, home_log_rate_shift, p_home "
            "FROM analysis.match_hindcasts"
        ) == [
            {
                "model_version": "v0.3.0",
                "match_id": match_id,
                "retrospective": True,
                "origin_at": datetime.fromisoformat("2026-08-15T00:00:00+01:00"),
                "model_results_cutoff": date(2026, 8, 15),
                "prospective_from": date(2026, 9, 17),
                "personnel_applied": True,
                "home_log_rate_shift": -0.08,
                "p_home": 0.5,
            }
        ]
        assert session.rows(
            "SELECT count(*) AS cells, round(sum(probability), 6) AS total "
            "FROM analysis.match_hindcast_score_grid"
        ) == [{"cells": 4, "total": 0.8}]
        assert session.rows(
            "SELECT outcome, home_goals, away_goals FROM analysis.match_hindcast_outcomes"
        ) == [{"outcome": "H", "home_goals": 2, "away_goals": 1}]
        assert session.rows(
            "SELECT count(*) AS n FROM analysis.match_hindcasts "
            "SEMI JOIN analysis.record_matches USING (match_id)"
        ) == [{"n": 0}]
    finally:
        session.close()


def test_a_match_hindcast_that_reaches_prospective_coverage_fails_the_session():
    match_id = "eng-premier-league:2026-2027:arsenal:chelsea"
    data, publish_store = match_hindcast_stores(match_id, match_date="2026-09-17")
    with pytest.raises(ValueError, match="reaches prospective coverage"):
        open_analysis_session(data_store=data, publish_store=publish_store)


def test_a_match_hindcast_that_is_also_a_prospective_row_fails_the_session():
    match_id = "eng-premier-league:2026-2027:arsenal:chelsea"
    data, publish_store = match_hindcast_stores(match_id)
    publish_store.objects["record.json"] = {
        "schema_version": 2,
        "updated_at": "2026-09-18T00:00:00+00:00",
        "pending": [
            {
                "match_id": match_id,
                "competition_id": "eng-premier-league",
                "season_id": "2026-2027",
                "forecast_id": "2026-09-17T144601Z",
                "generated_at": "2026-09-17T14:56:47+00:00",
                "kickoff_time": "2026-09-19T14:00:00+00:00",
                "model_version": "v0.3.0",
                "p_home": 0.5,
                "p_draw": 0.25,
                "p_away": 0.25,
            }
        ],
        "settled": [],
        "summary": {},
    }
    with pytest.raises(ValueError, match="also appears in the prospective record"):
        open_analysis_session(data_store=data, publish_store=publish_store)


def test_a_superseded_match_hindcast_version_is_not_loaded_by_default():
    data, publish_store = match_hindcast_stores("eng-premier-league:2026-2027:arsenal:chelsea")
    older = "match-hindcasts/v0.2/eng-premier-league/2026-2027.json"
    publish_store.objects[older] = match_hindcast_document(
        "eng-premier-league:2026-2027:arsenal:chelsea", model_version="v0.2"
    )
    publish_store.objects["match-hindcasts/index.json"]["seasons"].append(
        {"model_version": "v0.2", "href": older}
    )
    session = open_analysis_session(data_store=data, publish_store=publish_store)
    try:
        assert session.rows("SELECT DISTINCT model_version FROM analysis.match_hindcasts") == [
            {"model_version": "v0.3.0"}
        ]
    finally:
        session.close()
    assert older not in publish_store.reads


def test_the_published_score_grid_may_round_but_not_drift():
    """121 rounded cells drift by about 6e-5. A grid that misses by more is an error."""
    match_id = "eng-premier-league:2026-2027:arsenal:chelsea"
    for omitted, fails in ((0.20005, False), (0.21, True)):
        data, publish_store = match_hindcast_stores(match_id)
        grid = publish_store.objects[MATCH_HINDCAST_HREF]["matches"][0]["score_probabilities"]
        grid["omitted_probability"] = omitted
        if fails:
            with pytest.raises(ValueError, match="Invalid score distribution total"):
                open_analysis_session(data_store=data, publish_store=publish_store)
            continue
        session = open_analysis_session(data_store=data, publish_store=publish_store)
        session.close()


def test_a_partial_release_keeps_every_live_model_version():
    """One division can fail while the others publish, so the current versions can differ."""
    data, publish_store = hindcast_archive_stores()
    pointers = publish_store.objects["forecasts/current.json"]["forecasts"]
    pointers.append(
        {
            **pointers[0],
            "competition_id": "eng-championship",
            "competition_name": "Championship",
            "forecast_id": "2026-09-15T181554Z",
            "generated_at": "2026-09-15T18:20:38+00:00",
            "model_version": "v0.2",
            "href": "forecasts/eng-championship/2026-09-15T181554Z.json",
        }
    )
    session = open_analysis_session(data_store=data, publish_store=publish_store)
    try:
        assert session.rows(
            "SELECT DISTINCT model_version FROM analysis.hindcast_origins ORDER BY model_version"
        ) == [{"model_version": "v0.2"}, {"model_version": "v0.3.0"}]
        assert json.loads(
            session.rows("SELECT hindcast_model_versions FROM analysis.session")[0][
                "hindcast_model_versions"
            ]
        ) == ["v0.2", "v0.3.0"]
    finally:
        session.close()


def test_no_live_forecast_means_no_current_hindcast_generation():
    """`current` never quietly becomes `all`; the whole archive is an explicit request."""
    data, publish_store = hindcast_archive_stores()
    publish_store.objects["forecasts/current.json"] = {
        "schema_version": 1,
        "updated_at": "2026-09-17T15:00:00+00:00",
        "forecasts": [],
    }
    session = open_analysis_session(data_store=data, publish_store=publish_store)
    try:
        assert session.rows("SELECT count(*) AS n FROM analysis.hindcast_origins") == [{"n": 0}]
    finally:
        session.close()
    assert not any("/series.json" in key for key in publish_store.reads)


def test_a_changed_match_hindcast_document_rebuilds_the_session(tmp_path):
    """The index names the content, so a changed bridge selects a new file rather than the old."""
    match_id = "eng-premier-league:2026-2027:arsenal:chelsea"
    data, publish_store = match_hindcast_stores(match_id)
    directory = tmp_path / "sessions"
    first = open_analysis_session(
        data_store=data, publish_store=publish_store, session_directory=directory
    )
    try:
        assert first.rows("SELECT p_home FROM analysis.match_hindcasts") == [{"p_home": 0.5}]
    finally:
        first.close()

    changed_href = "match-hindcasts/v0.3.0/eng-premier-league/2026-2027/bbbb2222.json"
    changed = match_hindcast_document(match_id)
    changed["matches"][0].update(p_home=0.6, p_draw=0.2, p_away=0.2)
    publish_store.objects[changed_href] = changed
    publish_store.objects["match-hindcasts/index.json"]["seasons"] = [
        {"model_version": "v0.3.0", "href": changed_href}
    ]
    second = open_analysis_session(
        data_store=data, publish_store=publish_store, session_directory=directory
    )
    try:
        assert second.path != first.path
        assert second.rows("SELECT p_home FROM analysis.match_hindcasts") == [{"p_home": 0.6}]
    finally:
        second.close()


def test_a_score_grid_with_the_right_mass_but_the_wrong_shape_fails():
    """Total mass alone does not prove the grid; it must reproduce the published H/D/A split."""
    match_id = "eng-premier-league:2026-2027:arsenal:chelsea"
    data, publish_store = match_hindcast_stores(match_id)
    grid = publish_store.objects[MATCH_HINDCAST_HREF]["matches"][0]["score_probabilities"]
    # The same 0.8 of mass, moved from a home win into a draw.
    grid["grid_home_rows_away_columns"] = [[0.7, 0.05], [0.05, 0.0]]
    with pytest.raises(ValueError, match="does not reproduce its match-hindcast probabilities"):
        open_analysis_session(data_store=data, publish_store=publish_store)


def test_a_score_grid_that_matches_its_probabilities_passes():
    match_id = "eng-premier-league:2026-2027:arsenal:chelsea"
    data, publish_store = match_hindcast_stores(match_id)
    session = open_analysis_session(data_store=data, publish_store=publish_store)
    try:
        assert session.rows(
            "SELECT round(sum(probability) FILTER (home_goals > away_goals), 6) AS p_home "
            "FROM analysis.match_hindcast_score_grid"
        ) == [{"p_home": 0.4}]
    finally:
        session.close()
