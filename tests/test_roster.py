from datetime import date, timedelta

import pytest

from epl_forecast.research.personnel_mean import realized_continuity
from epl_forecast.research.roster import (
    BENCHED,
    DEPARTED,
    RETAINED,
    UNRESOLVED,
    RosterEvidence,
    continuity_components,
)
from epl_forecast.schema import Fixture, Match, fixture_id

TARGET = date(2025, 9, 1)


def spell(day, team, season="2025-2026"):
    return {"player_id": "p", "match_date": day, "team_id": team, "season_id": season}


def transfer(day, source, destination):
    return {
        "player_id": "p",
        "transfer_date": day,
        "from_team_id": source,
        "to_team_id": destination,
    }


def classify(spells, transfers, squad=()):
    return RosterEvidence(spells, transfers).classify("p", "home", TARGET, "2025-2026", set(squad))


def test_matchday_substitute_is_benched_not_departed():
    spells = [spell(date(2025, 8, 20), "home")]
    assert classify(spells, [transfer(date(2025, 8, 25), "home", "other")], {"p"}) == BENCHED


def test_transfer_after_last_appearance_is_departure():
    spells = [spell(date(2025, 8, 20), "home"), spell(date(2025, 10, 1), "home")]
    assert classify(spells, [transfer(date(2025, 8, 25), "home", "other")]) == DEPARTED


def test_transfer_before_last_appearance_is_not_departure():
    spells = [spell(date(2025, 8, 20), "home")]
    assert classify(spells, [transfer(date(2025, 8, 1), "home", "other")]) == UNRESOLVED


def test_return_from_loan_before_target_cancels_departure():
    spells = [spell(date(2025, 8, 10), "home"), spell(date(2025, 10, 1), "home")]
    transfers = [
        transfer(date(2025, 8, 15), "home", "other"),
        transfer(date(2025, 8, 30), "other", "home"),
    ]
    assert classify(spells, transfers) == RETAINED


def test_new_club_appearance_is_departure_without_a_transfer_record():
    spells = [spell(date(2025, 8, 10), "home"), spell(date(2025, 8, 24), "other")]
    assert classify(spells, []) == DEPARTED


def test_later_same_season_appearance_is_retained_and_otherwise_unresolved():
    assert classify([spell(date(2025, 8, 10), "home"), spell(date(2025, 9, 20), "home")], []) == (
        RETAINED
    )
    later_season = spell(date(2026, 8, 20), "home", "2026-2027")
    assert classify([spell(date(2025, 8, 10), "home"), later_season], []) == UNRESOLVED


def test_components_sum_to_realized_starting_xi_discontinuity():
    matches, rows, squads = [], [], []
    start = date(2025, 8, 1)
    for index in range(9):
        match_id = fixture_id("eng-premier-league", "2025-2026", "home", f"away-{index}")
        day = start + timedelta(days=7 * index)
        fixture = Fixture(match_id, "eng-premier-league", "2025-2026", day, "home", f"away-{index}")
        matches.append(Match(fixture, 1, 0, "a" * 64, index, str(day + timedelta(days=1))))
        for team in ("home", f"away-{index}"):
            players = [f"{team}-{number}" for number in range(11)]
            if index == 8 and team == "home":
                players = players[:8] + ["new-1", "new-2", "new-3"]
            for player in players:
                row = {
                    "match_id": match_id,
                    "team_id": team,
                    "player_id": player,
                    "minutes": 90,
                    "starts": True,
                }
                rows.append(row)
                squads.append({**row, "match_date": day, "season_id": "2025-2026", "starts": True})
    target = matches[8].fixture
    squads.append(
        {
            "match_id": target.match_id,
            "team_id": "home",
            "player_id": "home-8",
            "match_date": target.match_date,
            "season_id": "2025-2026",
            "starts": False,
        }
    )
    transfers = [
        {
            "player_id": "home-9",
            "transfer_date": target.match_date - timedelta(days=2),
            "from_team_id": "home",
            "to_team_id": "elsewhere",
        }
    ]
    components = continuity_components(matches, rows, squads, transfers)[target.match_id, "home"]
    expected = realized_continuity(matches, rows)[target.match_id, "home"]
    assert components["d"] == pytest.approx(expected)
    assert components[BENCHED] == pytest.approx(1 / 11)
    assert components[DEPARTED] == pytest.approx(1 / 11)
    assert components[UNRESOLVED] == pytest.approx(1 / 11)
    assert sum(components[label] for label in (BENCHED, DEPARTED, RETAINED, UNRESOLVED)) == (
        pytest.approx(expected)
    )
