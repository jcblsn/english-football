import json

from epl_forecast.analysis import open_analysis_session
from epl_forecast.datasets import publish


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

    def configure_duckdb(self, connection):
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
