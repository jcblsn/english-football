import json

from epl_forecast.data.understat_ingest import ingest
from epl_forecast.datasets import Dataset, publish


def test_understat_uses_retained_exact_names_without_future_or_ambiguous_links(tmp_path):
    request = {
        "provider": "api_football",
        "retrieved_at": "2026-09-01T12:00:00+00:00",
        "source_sha256": "a" * 64,
        "evidence_basis": "retrospective",
        "context": {},
    }
    fixture = {
        "match_id": "m",
        "competition_id": "eng-premier-league",
        "season_id": "2023-2024",
        "home_team_id": "a",
        "away_team_id": "b",
        "match_date": "2024-05-01",
        "status": "finished",
        "stage": "regular",
        "home_goals": 0,
        "away_goals": 0,
    }
    publish(
        tmp_path,
        request,
        {
            "fixtures": [fixture],
            "players": [
                {"player_id": "p1", "name": "Pau Francisco Torres", "birth_date": "1997-01-16"},
                {"player_id": "p2", "name": "Other Person"},
                {"player_id": "p3", "name": "Same Name"},
                {"player_id": "p4", "name": "Same Name"},
            ],
            "appearances": [
                {"match_id": "m", "player_id": player, "team_id": "a"}
                for player in ("p1", "p2", "p3", "p4")
            ],
        },
    )
    publish(
        tmp_path,
        {**request, "source_sha256": "b" * 64},
        {"players": [{"player_id": "p1", "name": "Pau Torres"}]},
    )
    publish(
        tmp_path,
        {**request, "retrieved_at": "2026-09-09T12:00:00+00:00", "source_sha256": "c" * 64},
        {"players": [{"player_id": "p2", "name": "Future Name", "understat_id": "2"}]},
    )
    roster = {
        str(i): {
            "player_id": str(i),
            "player": name,
            "position": "DC",
            "time": "90",
            "xG": "0",
            "xA": "0",
            "shots": "0",
        }
        for i, name in enumerate(("Pau Torres", "Future Name", "Same Name"), 1)
    }
    source = {
        **request,
        "provider": "understat",
        "retrieved_at": "2026-09-08T12:00:00+00:00",
        "source_sha256": "d" * 64,
        "context": {"kind": "players", "match_id": "m"},
    }
    ingest(tmp_path, source, json.dumps({"rosters": {"h": roster, "a": {}}}).encode())
    data = Dataset(workspace=tmp_path)
    try:
        records = {
            r["understat_id"]: r["player_id"] for r in data.rows("SELECT * FROM player_process")
        }
        assert records == {"1": "p1", "2": None, "3": None}
        assert (
            data.rows("SELECT name FROM players WHERE player_id='p1'")[0]["name"]
            == "Pau Francisco Torres"
        )
    finally:
        data.close()


def _understat_payload(match_id):
    return json.dumps(
        {
            "rosters": {
                "h": {
                    "1": {
                        "player_id": "9001",
                        "player": "Kai Havertz",
                        "position": "FW",
                        "time": "90",
                        "xG": "0.7",
                        "xA": "0.1",
                        "shots": "3",
                    }
                },
                "a": {
                    "2": {
                        "player_id": "9002",
                        "player": "Cole Palmer",
                        "position": "AMC",
                        "time": "80",
                        "xG": "0.3",
                        "xA": "0.4",
                        "shots": "2",
                    }
                },
            }
        }
    ).encode()


def _seed(root, matches):
    from epl_forecast.datasets import publish

    request = {
        "provider": "api_football",
        "retrieved_at": "2026-01-01T00:00:00+00:00",
        "evidence_basis": "retrospective",
        "source_sha256": "b" * 64,
        "context": {"endpoint": "fixtures"},
    }
    fixtures, appearances, names = [], [], {}
    for index, (match_id, home, away) in enumerate(matches):
        fixtures.append(
            {
                "match_id": match_id,
                "competition_id": "eng-premier-league",
                "season_id": "2023-2024",
                "stage": "regular",
                "home_team_id": home,
                "away_team_id": away,
                "match_date": f"2024-01-{index + 1:02d}",
                "status": "finished",
                "home_goals": 1,
                "away_goals": 0,
            }
        )
        for team, player, name in (
            (home, "p1", "Kai Havertz"),
            (away, "p2", "Cole Palmer"),
        ):
            appearances.append(
                {
                    "match_id": match_id,
                    "player_id": player,
                    "team_id": team,
                    "competition_id": "eng-premier-league",
                    "season_id": "2023-2024",
                    "kickoff_time": f"2024-01-{index + 1:02d}T15:00:00+00:00",
                    "position": "FWD",
                    "starts": 1,
                    "minutes": 90,
                }
            )
            names[player] = name
    publish(
        root,
        request,
        {
            "fixtures": fixtures,
            "appearances": appearances,
            "players": [{"player_id": k, "name": v} for k, v in sorted(names.items())],
        },
    )


def test_shared_ingest_context_matches_one_dataset_read_per_match(tmp_path):
    from epl_forecast.data.understat_ingest import IngestContext, ingest
    from epl_forecast.datasets import Dataset

    matches = [
        (f"eng-premier-league:2023-2024:arsenal:chelsea-{i}", "arsenal", "chelsea")
        for i in range(4)
    ]
    records = [
        {
            "provider": "understat",
            "url": f"https://understat.com/getMatchData/{i}",
            "retrieved_at": f"2026-02-0{i + 1}T00:00:00+00:00",
            "evidence_basis": "retrospective",
            "source_sha256": f"{i}" * 64,
            "raw_path": "raw/understat/x.json",
            "context": {"kind": "players", "match_id": match_id},
        }
        for i, (match_id, _, _) in enumerate(matches)
    ]

    def run(root, shared):
        _seed(root, matches)
        context = IngestContext(root) if shared else None
        for record in records:
            ingest(root, record, _understat_payload(record["context"]["match_id"]), context)
        data = Dataset(workspace=root)
        try:
            return data.rows(
                "SELECT match_id, understat_id, player_id, minutes, xg, xa, shots "
                "FROM player_process ORDER BY match_id, understat_id"
            )
        finally:
            data.close()

    direct = run(tmp_path / "direct", False)
    shared = run(tmp_path / "shared", True)
    assert direct == shared
    assert len(direct) == 8
    assert all(row["player_id"] is not None for row in direct)


def test_a_later_capture_of_the_same_appearance_does_not_hide_an_earlier_one(tmp_path):
    """A replay holds later captures; linking must still see what existed at the capture time."""
    from epl_forecast.data.understat_ingest import IngestContext

    fixture = {
        "match_id": "m",
        "competition_id": "eng-premier-league",
        "season_id": "2026-2027",
        "home_team_id": "a",
        "away_team_id": "b",
        "match_date": "2026-09-01",
        "status": "finished",
        "stage": "regular",
        "home_goals": 0,
        "away_goals": 0,
    }

    def api(retrieved_at, source, basis):
        return {
            "provider": "api_football",
            "retrieved_at": retrieved_at,
            "source_sha256": source * 64,
            "evidence_basis": basis,
            "context": {},
        }

    understat = {
        "provider": "understat",
        "retrieved_at": "2026-09-08T12:00:00+00:00",
        "source_sha256": "d" * 64,
        "evidence_basis": "captured",
        "context": {"kind": "players", "match_id": "m"},
    }
    roster = {
        "7": {
            "player_id": "7",
            "player": "Player Seven",
            "position": "DC",
            "time": "90",
            "xG": "0",
            "xA": "0",
            "shots": "0",
        }
    }
    payload = json.dumps({"rosters": {"h": roster, "a": {}}}).encode()
    for shared in (False, True):
        root = tmp_path / ("shared" if shared else "direct")
        publish(
            root,
            api("2026-09-02T12:00:00+00:00", "a", "retrospective"),
            {
                "fixtures": [fixture],
                "players": [{"player_id": "p7", "name": "Player Seven"}],
                "appearances": [{"match_id": "m", "player_id": "p7", "team_id": "a"}],
            },
        )
        publish(
            root,
            api("2026-09-11T12:00:00+00:00", "b", "captured"),
            {"appearances": [{"match_id": "m", "player_id": "p7", "team_id": "a", "minutes": 90}]},
        )
        ingest(root, understat, payload, IngestContext(root) if shared else None)
        data = Dataset(workspace=root)
        try:
            assert data.rows("SELECT player_id FROM player_process") == [{"player_id": "p7"}], (
                shared
            )
        finally:
            data.close()
