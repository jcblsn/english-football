import json

import pytest
from test_publication import sample_forecast, sample_run

from epl_forecast.analysis import open_analysis_session, start_ui
from epl_forecast.datasets import publish
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
    session = open_analysis_session(
        data_store=store, include_derived=False, root=tmp_path / "empty"
    )
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
        root=local,
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
    session = open_analysis_session(
        data_store=Store(remote, [old, empty]), include_derived=False, root=tmp_path / "empty"
    )
    try:
        assert session.rows(
            "SELECT team_id, row_count, player_id FROM analysis.squad_memberships"
        ) == [{"team_id": "arsenal", "row_count": 0, "player_id": None}]
    finally:
        session.close()


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


def test_forecasts_follow_archive_pointers_and_keep_private_matches_distinct(tmp_path):
    data, publish_store = forecast_stores()
    data.objects["runs/forecasts/failed/eng-premier-league/forecast.json"] = {"schema_version": 1}
    session = open_analysis_session(
        data_store=data, publish_store=publish_store, root=tmp_path / "empty"
    )
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


def test_a_successful_public_forecast_requires_its_private_run(tmp_path):
    data, publish_store = forecast_stores()
    del data.objects["runs/forecasts/2026-09-10T120000Z/eng-premier-league/forecast.json"]
    with pytest.raises(ValueError, match="pointer does not resolve"):
        open_analysis_session(data_store=data, publish_store=publish_store, root=tmp_path / "empty")


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
    session = open_analysis_session(
        data_store=data, publish_store=publish_store, root=tmp_path / "empty"
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
