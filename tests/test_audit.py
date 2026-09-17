from epl_forecast.data import collect
from epl_forecast.datasets import publish


class Store:
    def __init__(self, directory):
        self.directory = directory
        self.manifests = []
        self.written = {}

    def publish(self, request, tables):
        self.manifests.append(publish(self.directory, request, tables))

    def get_json(self, key, default=None):
        if key == "state/manifests.json":
            return {"manifests": self.manifests}
        return default

    def put_json(self, key, value):
        self.written[key] = value

    def get_bytes(self, key):
        return (self.directory / key).read_bytes()

    def uri(self, key):
        return str(self.directory / key)

    def configure_duckdb(self, connection):
        pass


def evidence(endpoint=None, player=None):
    context = {}
    if endpoint is not None:
        context["endpoint"] = endpoint
    if player is not None:
        context["player"] = player
    return {
        "provider": "api_football",
        "retrieved_at": "2026-09-08T12:00:00+00:00",
        "evidence_basis": "retrospective",
        "source_sha256": f"{endpoint}{player}".ljust(64, "a"),
        "context": context,
    }


def readiness_fixture(home, away, home_starters, away_starters, season="2026-2027"):
    competition = "eng-premier-league"
    match_id = f"{competition}:{season}:{home}:{away}"
    common = {"match_id": match_id, "competition_id": competition, "season_id": season}
    appearances = [
        {
            **common,
            "player_id": f"p{team}{index}",
            "team_id": team,
            "starts": 1,
            "minutes": 90 if index < usable else None,
        }
        for team, count, usable in ((home, *home_starters), (away, *away_starters))
        for index in range(count)
    ]
    return {
        "fixtures": [
            {
                **common,
                "stage": "regular",
                "status": "finished",
                "home_team_id": home,
                "away_team_id": away,
                "match_date": "2026-08-15",
                "home_goals": 1,
                "away_goals": 0,
            }
        ],
        "appearances": appearances,
        "players": [
            {"player_id": r["player_id"], "api_id": index, "name": f"Player {index}"}
            for index, r in enumerate(appearances, start=1)
        ],
    }


def test_archive_audit_reads_r2_and_separates_uncovered_seasons_from_defective_captures(tmp_path):
    store = Store(tmp_path / "remote")
    store.publish(evidence(), readiness_fixture("a", "b", (11, 11), (11, 11)))
    store.publish(evidence(), readiness_fixture("c", "d", (11, 0), (11, 11)))
    uncovered = readiness_fixture("e", "f", (0, 0), (0, 0))
    uncovered["appearances"] = []
    uncovered["players"] = []
    store.publish(evidence(), uncovered)
    written = collect.audit(store)
    assert store.written["audits/coverage.json"] == written
    report = written["incomplete_starting_lineups"]
    assert report["fixtures"] == 2
    assert report["by_season"] == {
        "eng-premier-league/2026-2027": {"fixtures": 2, "without_any_appearance": 1}
    }
    assert [r["match_id"] for r in report["examples"]] == ["eng-premier-league:2026-2027:c:d"]
