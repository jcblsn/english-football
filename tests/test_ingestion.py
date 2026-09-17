from epl_forecast.data import api_football as api
from epl_forecast.datasets import Dataset


def squad_record(time):
    return {
        "provider": "api_football",
        "retrieved_at": time,
        "evidence_basis": "captured",
        "source_sha256": time.encode().hex().ljust(64, "0")[:64],
        "context": {
            "endpoint": "players/squads",
            "team": 42,
            "season_id": "2026-2027",
            "competition_id": "eng-premier-league",
        },
    }


def test_conflicting_squad_positions_are_unknown(tmp_path):
    body = {
        "response": [
            {
                "team": {"id": 42, "name": "Arsenal"},
                "players": [
                    {"id": 1, "name": "Player One", "position": "Defender"},
                    {"id": 1, "name": "Player One", "position": "Midfielder"},
                ],
            }
        ]
    }
    api.normalize(squad_record("2026-09-08T10:00:00+00:00"), body, tmp_path)
    data = Dataset(workspace=tmp_path)
    assert data.rows("SELECT position FROM memberships") == [{"position": "UNK"}]
    data.close()


def test_inconsistent_shot_pair_is_audited_without_discarding_result(tmp_path):
    from epl_forecast.data.football_data import ingest

    record = {
        "provider": "football_data",
        "retrieved_at": "2026-09-08T10:00:00+00:00",
        "evidence_basis": "retrospective",
        "source_sha256": "a" * 64,
        "context": {
            "season_start": 2024,
            "season_id": "2024-2025",
            "competition_id": "eng-premier-league",
            "division": "E0",
        },
    }
    payload = (
        b"Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HS,HST,AS,AST\n"
        b"E0,01/09/2024,Arsenal,Chelsea,1,0,H,2,7,10,3\n"
    )
    manifest = ingest(tmp_path, record, payload)
    assert len(manifest["request"]["normalization_issues"]) == 1
    data = Dataset(workspace=tmp_path)
    assert len(data.matches()) == 1
    assert data.rows("SELECT shots, shots_on_target FROM team_process WHERE team_id='arsenal'") == [
        {"shots": None, "shots_on_target": None}
    ]
    assert data.rows("SELECT shots, shots_on_target FROM team_process WHERE team_id='chelsea'") == [
        {"shots": 10, "shots_on_target": 3}
    ]
    data.close()


def test_fpl_identity_uses_unique_captured_team_and_birth_date(tmp_path):
    import json

    from epl_forecast.data import fpl
    from epl_forecast.datasets import publish

    record = squad_record("2026-09-08T10:00:00+00:00")
    api.normalize(
        record,
        {
            "response": [
                {
                    "team": {"id": 42, "name": "Arsenal"},
                    "players": [
                        {"id": i, "name": f"API Player {i}", "position": "Defender"}
                        for i in (1, 2, 3)
                    ],
                }
            ]
        },
        tmp_path,
    )
    publish(
        tmp_path,
        {**record, "context": {"endpoint": "players"}},
        {
            "players": [
                {
                    "player_id": f"p{i}",
                    "api_id": i,
                    "name": f"Full API Name {i}",
                    "birth_date": "2000-01-01" if i == 1 else "2000-01-02",
                }
                for i in (1, 2, 3)
            ]
        },
    )
    body = {
        "teams": [{"id": 1, "name": "Arsenal"}],
        "events": [],
        "elements": [
            {
                "code": code,
                "element_type": 2,
                "first_name": "Full",
                "second_name": "Name",
                "birth_date": birthday,
                "team": 1,
                "status": "a",
                "news": "",
            }
            for code, birthday in ((100, "2000-01-01"), (200, "2000-01-02"))
        ],
    }
    fpl.ingest(
        tmp_path,
        {
            **record,
            "provider": "fpl",
            "retrieved_at": "2026-09-08T11:00:00+00:00",
            "context": {"season_id": "2026-2027"},
        },
        json.dumps(body).encode(),
    )
    data = Dataset(workspace=tmp_path)
    assert data.rows("SELECT fpl_code, player_id FROM availability ORDER BY fpl_code") == [
        {"fpl_code": "100", "player_id": "p1"},
        {"fpl_code": "200", "player_id": None},
    ]
    data.close()


def test_transfers_do_not_identify_foreign_clubs_by_name(tmp_path):
    record = squad_record("2026-09-08T10:00:00+00:00")
    api.normalize(
        record, {"response": [{"team": {"id": 42, "name": "Arsenal"}, "players": []}]}, tmp_path
    )
    api.normalize(
        {**record, "context": {"endpoint": "transfers", "player": 1}},
        {
            "response": [
                {
                    "player": {"id": 1, "name": "Player One"},
                    "transfers": [
                        {
                            "date": "2026-08-01",
                            "type": "Loan",
                            "teams": {
                                "out": {"id": 999, "name": "Arsenal"},
                                "in": {"id": 42, "name": "Arsenal"},
                            },
                        }
                    ],
                }
            ]
        },
        tmp_path,
    )
    data = Dataset(workspace=tmp_path)
    assert data.rows("SELECT from_team_id, to_team_id FROM transfers") == [
        {"from_team_id": "af-team-999", "to_team_id": "arsenal"}
    ]
    assert data.rows("SELECT player_id FROM players") == [{"player_id": "p1"}]
    data.close()


def test_api_player_aliases_and_zero_ids_are_explicit():
    assert api.player_id(531386) == api.player_id(297641) == "p297641"
    assert api.canonical_api_id(531386) == 297641
    assert api.player_id(0) is None
    assert api.compatible_name("J. Metcalfe", "Jenson Metcalfe")
    assert not api.compatible_name("T. Collyer", "Carlos Baleba")
    assert not (set(api.PLAYER_ALIASES) & set(api.PLAYER_ALIASES.values()))


def test_every_alias_records_same_fixture_shirt_number_evidence():
    import csv
    from pathlib import Path

    with (Path(api.__file__).parent / "api_player_aliases.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == len(api.PLAYER_ALIASES)
    for row in rows:
        assert int(row["alias_api_id"]) != int(row["api_id"])
        assert int(row["fixture_id"]) > 0 and int(row["team_api_id"]) > 0
        assert int(row["shirt_number"]) > 0
        assert len(row["source_sha256"]) == 64
    assert len({int(r["alias_api_id"]) for r in rows}) == len(rows)


def test_identity_collisions_ignore_distinct_teammates():
    from epl_forecast.data.collect import same_named_player

    assert same_named_player("T. Ndiaye", "Talla Ndiaye")
    assert same_named_player("Timur Tuterov", "T. Tuterov")
    assert not same_named_player("William Thomas Alves", "William Thomas Fish")
    assert not same_named_player("Jamal Akua Lowe", "Max Josef Lowe")
    assert not same_named_player("Talla Ndiaye", "")


def test_disputed_sidelined_end_is_unknown_with_retained_issue(tmp_path):
    from copy import deepcopy

    record = {
        **squad_record("2026-09-08T10:00:00+00:00"),
        "context": {"endpoint": "sidelined", "player": 19558},
    }
    body = {
        "response": [
            {"type": "Suspended", "start": "2018-02-14", "end": "2018-02-25"},
            {"type": "Suspended", "start": "2018-02-14", "end": "2018-02-20"},
            {"type": "Hamstring", "start": "2018-02-14", "end": "2018-03-01"},
        ]
    }
    original = deepcopy(body)
    manifest = api.normalize(record, body, tmp_path)
    assert body == original and "normalization_issues" not in record
    assert manifest == api.normalize(record, body, tmp_path)
    issues = manifest["request"]["normalization_issues"]
    assert len(issues) == 1 and issues[0]["reported_values"] == ["2018-02-20", "2018-02-25"]
    data = Dataset(workspace=tmp_path)
    assert data.rows(
        "SELECT reason, end_date IS NULL AS unknown_end FROM availability ORDER BY reason"
    ) == [
        {"reason": "Hamstring", "unknown_end": False},
        {"reason": "Suspended", "unknown_end": True},
    ]
    data.close()


def test_identity_keys_are_reused_until_a_fixture_publication(tmp_path):
    from epl_forecast.data import api_football
    from epl_forecast.datasets import publish

    api_football._IDENTITY_KEYS.clear()
    (tmp_path / "manifests").mkdir(parents=True)
    first = api_football.identity_keys(tmp_path)
    assert api_football.identity_keys(tmp_path) is first
    publish(
        tmp_path,
        {
            "provider": "api_football",
            "retrieved_at": "2026-01-01T00:00:00+00:00",
            "evidence_basis": "retrospective",
            "source_sha256": "a" * 64,
            "context": {"endpoint": "fixtures"},
        },
        {
            "fixtures": [
                {
                    "match_id": "eng-premier-league:2025-2026:arsenal:chelsea",
                    "competition_id": "eng-premier-league",
                    "season_id": "2025-2026",
                    "stage": "regular",
                    "home_team_id": "arsenal",
                    "away_team_id": "chelsea",
                    "status": "finished",
                    "home_goals": 1,
                    "away_goals": 0,
                    "api_id": 5150,
                }
            ]
        },
    )
    refreshed = api_football.identity_keys(tmp_path)
    assert refreshed is not first
    assert refreshed[1] == {5150: "eng-premier-league:2025-2026:arsenal:chelsea"}


def test_identity_cache_matches_a_rebuild_after_a_transfer_publishes_a_team(tmp_path):
    from epl_forecast.data import api_football

    request = {
        "provider": "api_football",
        "retrieved_at": "2026-01-01T00:00:00+00:00",
        "evidence_basis": "retrospective",
        "source_sha256": "c" * 64,
        "context": {"endpoint": "transfers"},
    }
    body = {
        "response": [
            {
                "player": {"id": 700, "name": "A Player"},
                "transfers": [
                    {
                        "date": "2025-01-05",
                        "type": "Loan",
                        "teams": {
                            "in": {"id": 9001, "name": "Unmapped In"},
                            "out": {"id": 9002, "name": "Unmapped Out"},
                        },
                    }
                ],
            }
        ]
    }
    api_football._IDENTITY_KEYS.clear()
    (tmp_path / "manifests").mkdir(parents=True)
    api_football.normalize(request, body, tmp_path)
    cached = api_football.identity_keys(tmp_path)[0]
    api_football._IDENTITY_KEYS.clear()
    rebuilt = api_football.identity_keys(tmp_path)[0]
    assert cached == rebuilt
    assert rebuilt[9001] == "af-team-9001"


def fixture_record(time="2026-09-08T10:00:00+00:00"):
    return {
        "provider": "api_football",
        "retrieved_at": time,
        "evidence_basis": "retrospective",
        "source_sha256": time.encode().hex().ljust(64, "0")[:64],
        "context": {"endpoint": "fixtures"},
    }


def fixture_body(statistics):
    return {
        "response": [
            {
                "fixture": {
                    "id": 900001,
                    "date": "2026-08-15T14:00:00+00:00",
                    "status": {"short": "FT"},
                },
                "league": {"id": 40, "season": 2026, "round": "Regular Season - 1"},
                "teams": {
                    "home": {"id": 41, "name": "Swansea"},
                    "away": {"id": 54, "name": "Birmingham"},
                },
                "goals": {"home": 2, "away": 1},
                "statistics": statistics,
            }
        ]
    }


def test_team_match_statistics_keep_percentages_and_absent_counts_apart(tmp_path):
    body = fixture_body(
        [
            {
                "team": {"id": 41, "name": "Swansea"},
                "statistics": [
                    {"type": "Total Shots", "value": 14},
                    {"type": "Shots on Goal", "value": 5},
                    {"type": "Ball Possession", "value": "57%"},
                    {"type": "expected_goals", "value": "1.83"},
                    {"type": "Red Cards", "value": None},
                    {"type": "Unmapped Provider Metric", "value": 3},
                ],
            },
            {
                "team": {"id": 54, "name": "Birmingham"},
                "statistics": [
                    {"type": "Total Shots", "value": 9},
                    {"type": "Shots on Goal", "value": 2},
                    {"type": "Ball Possession", "value": "43%"},
                ],
            },
        ]
    )
    api.normalize(fixture_record(), body, tmp_path)
    data = Dataset(workspace=tmp_path)
    rows = {r["team_id"]: r for r in data.rows("SELECT * FROM team_statistics ORDER BY team_id")}
    data.close()
    assert set(rows) == {"swansea-city", "birmingham-city"}
    home = rows["swansea-city"]
    assert (home["shots_total"], home["shots_on_goal"]) == (14, 5)
    assert home["possession"] == 57.0
    assert home["expected_goals"] == 1.83
    assert home["red_cards"] is None
    assert rows["birmingham-city"]["expected_goals"] is None


def test_a_fixture_without_team_statistics_publishes_none(tmp_path):
    api.normalize(fixture_record(), fixture_body([]), tmp_path)
    data = Dataset(workspace=tmp_path)
    assert data.rows("SELECT count(*) AS n FROM team_statistics") == [{"n": 0}]
    data.close()


def test_an_empty_fixture_detail_response_records_each_club_scope(tmp_path):
    api.normalize(fixture_record(), fixture_body([]), tmp_path)
    detail = {
        **fixture_record("2026-09-08T11:00:00+00:00"),
        "context": {"endpoint": "fixtures", "ids": "900001"},
    }
    api.normalize(detail, {"response": []}, tmp_path)
    data = Dataset(workspace=tmp_path)
    rows = data.rows("SELECT match_id, team_id, row_count FROM source_snapshots ORDER BY team_id")
    data.close()
    assert rows == [
        {
            "match_id": "eng-championship:2026-2027:swansea-city:birmingham-city",
            "team_id": "birmingham-city",
            "row_count": 0,
        },
        {
            "match_id": "eng-championship:2026-2027:swansea-city:birmingham-city",
            "team_id": "swansea-city",
            "row_count": 0,
        },
    ]


def test_a_reviewed_disputed_fixture_keeps_its_result_unknown(tmp_path, monkeypatch):
    import pytest

    key = "eng-championship:2026-2027:swansea-city:birmingham-city"
    monkeypatch.setattr(
        api, "FIXTURE_DISPUTES", {900001: {"match_id": key, "resolution": "unknown: test"}}
    )
    manifest = api.normalize(fixture_record(), fixture_body([]), tmp_path)
    data = Dataset(workspace=tmp_path)
    (row,) = data.rows("SELECT * FROM fixtures")
    data.close()
    assert (row["status"], row["home_goals"], row["match_date"]) == ("disputed", None, None)
    (issue,) = manifest["request"]["normalization_issues"]
    assert issue["match_id"] == key and issue["reported_values"]["home_goals"] == 2
    monkeypatch.setattr(
        api, "FIXTURE_DISPUTES", {900001: {"match_id": "another", "resolution": "unknown"}}
    )
    with pytest.raises(ValueError, match="another match"):
        api.normalize(fixture_record("2026-09-09T10:00:00+00:00"), fixture_body([]), tmp_path)


def test_latest_odds_without_a_captured_schedule_stay_unlinked(tmp_path):
    from epl_forecast.data import football_data
    from epl_forecast.datasets import publish

    evidence = {
        "provider": "api_football",
        "retrieved_at": "2026-08-13T10:00:00+00:00",
        "evidence_basis": "captured",
        "source_sha256": "a" * 64,
        "context": {},
    }
    fixture = {
        "match_id": "eng-premier-league:2026-2027:arsenal:chelsea",
        "competition_id": "eng-premier-league",
        "season_id": "2026-2027",
        "stage": "regular",
        "home_team_id": "arsenal",
        "away_team_id": "chelsea",
        "match_date": "2026-08-15",
        "status": "scheduled",
    }
    publish(tmp_path, evidence, {"fixtures": [fixture]})
    payload = (
        b"Div,Date,HomeTeam,AwayTeam,B365H,B365D,B365A\n"
        b"E0,15/08/2026,Arsenal,Chelsea,2.1,3.4,3.6\n"
        b"E2,15/08/2026,Barnet,Bromley,2.5,3.2,2.9\n"
    )
    record = {
        "provider": "football_data",
        "retrieved_at": "2026-08-14T10:00:00+00:00",
        "evidence_basis": "captured",
        "source_sha256": "b" * 64,
        "context": {"kind": "latest_odds", "season_id": "2026-2027"},
    }
    manifest = football_data.ingest(tmp_path, record, payload)
    data = Dataset(workspace=tmp_path)
    odds = data.rows("SELECT match_id FROM odds")
    data.close()
    assert odds == [{"match_id": fixture["match_id"]}]
    (issue,) = manifest["request"]["normalization_issues"]
    assert (issue["competition_id"], issue["rows"]) == ("eng-league-one", 1)


def test_a_squad_entry_without_a_provider_id_is_unknown(tmp_path):
    body = {
        "response": [
            {
                "team": {"id": 42, "name": "Swansea"},
                "players": [
                    {"id": None, "name": "Oliver Hall", "position": "Midfielder"},
                    {"id": 7, "name": "Known Player", "position": "Defender"},
                ],
            }
        ]
    }
    manifest = api.normalize(squad_record("2026-09-11T14:00:00+00:00"), body, tmp_path)
    data = Dataset(workspace=tmp_path)
    members = data.rows("SELECT player_id FROM memberships")
    data.close()
    assert members == [{"player_id": "p7"}]
    (issue,) = manifest["request"]["normalization_issues"]
    assert issue["reported_values"]["name"] == "Oliver Hall"
