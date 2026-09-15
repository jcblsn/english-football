from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from epl_forecast.datasets import Dataset, publish
from epl_forecast.models import make_model
from epl_forecast.models.poisson import PoissonMixture
from epl_forecast.research.personnel import (
    DEPARTED,
    MAX_UNRESOLVED,
    MEMBER,
    UNKNOWN,
    Evidence,
    candidate_shift,
    load_evidence,
    load_propensity,
    realized_discontinuity,
    structural_spec,
    team_expected,
)
from epl_forecast.research.personnel_mean import realized_continuity, shifted_scores
from epl_forecast.schema import Fixture, Match

COMPETITION = "eng-premier-league"
SEASON = "2026-2027"
KICKOFF = datetime(2026, 9, 19, 14, tzinfo=UTC)
CUTOFF = KICKOFF - timedelta(days=3)
BEFORE = CUTOFF - timedelta(hours=2)
AFTER = CUTOFF + timedelta(hours=2)
TARGET = f"{COMPETITION}:{SEASON}:home:away"
PROPENSITY = {
    "xi": {(n, last): 0.1 + 0.1 * n for n in range(9) for last in (False, True)},
    "squad": {(n, last): 0.2 + 0.1 * n for n in range(9) for last in (False, True)},
}
REGULARS = [f"home-{number}" for number in range(11)]


def appearance(match_id, team, player, kickoff, starts, minutes, retrieved_at=None):
    return {
        "match_id": match_id,
        "team_id": team,
        "player_id": player,
        "starts": starts,
        "minutes": minutes,
        "kickoff_time": kickoff,
        "match_date": kickoff.date(),
        "retrieved_at": retrieved_at or kickoff + timedelta(hours=3),
    }


def history(team="home"):
    rows, previous, matches = [], [], []
    for index in range(8):
        match_id = f"{COMPETITION}:{SEASON}:{team}:opponent-{index}"
        kickoff = datetime(2026, 8, 1, 14, tzinfo=UTC) + timedelta(days=5 * index)
        previous.append(match_id)
        fixture = Fixture(match_id, COMPETITION, SEASON, kickoff.date(), team, f"opponent-{index}")
        matches.append(Match(fixture, 1, 0, "a" * 64, index, ""))
        rows.extend(appearance(match_id, team, f"{team}-{n}", kickoff, True, 90) for n in range(11))
    return rows, previous, matches


def squad(team, players, retrieved_at=BEFORE):
    return [{"team_id": team, "player_id": p, "retrieved_at": retrieved_at} for p in players]


def transfer(player, source, destination, day, retrieved_at=BEFORE):
    return {
        "player_id": player,
        "transfer_date": day,
        "from_team_id": source,
        "to_team_id": destination,
        "retrieved_at": retrieved_at,
    }


def fpl(player, team, status, retrieved_at=BEFORE):
    return {
        "player_id": player,
        "team_id": team,
        "status": status,
        "reason": "",
        "chance_this_round": None,
        "chance_next_round": None,
        "retrieved_at": retrieved_at,
    }


def injury(player, team, status, match_id=TARGET, retrieved_at=BEFORE):
    return {
        "match_id": match_id,
        "team_id": team,
        "player_id": player,
        "competition_id": COMPETITION,
        "status": status,
        "reason": "Injury",
        "retrieved_at": retrieved_at,
    }


def expected(evidence, previous):
    return team_expected(evidence, "home", TARGET, COMPETITION, previous, PROPENSITY)


def test_post_cutoff_observations_cannot_change_the_estimate():
    rows, previous, _ = history()
    base = {"appearances": rows, "squads": squad("home", REGULARS)}
    later_match = f"{COMPETITION}:{SEASON}:home:later"
    later = {
        "appearances": rows
        + [appearance(later_match, "home", "new-1", AFTER - timedelta(hours=1), True, 90, AFTER)],
        "squads": base["squads"] + squad("other", ["home-0"], retrieved_at=AFTER),
        "transfers": [transfer("home-0", "home", "other", CUTOFF.date(), retrieved_at=AFTER)],
        "injuries": [injury("home-1", "home", "unavailable", retrieved_at=AFTER)],
        "fpl": [fpl("home-2", "home", "i", retrieved_at=AFTER)],
    }
    assert expected(Evidence(CUTOFF, **later), previous) == expected(
        Evidence(CUTOFF, **base), previous
    )


def test_realized_labels_exclude_substitutes_only_from_the_starting_xi():
    rows, previous, matches = history()
    starters = REGULARS[:8] + ["new-1", "new-2", "new-3"]
    final = [appearance(TARGET, "home", p, KICKOFF, True, 90) for p in starters] + [
        appearance(TARGET, "home", p, KICKOFF, False, 30) for p in REGULARS[8:]
    ]
    weights = Evidence(CUTOFF, appearances=rows).recent_weights("home", previous)
    xi = realized_discontinuity(weights, set(starters))
    assert xi == pytest.approx(3 / 11)
    assert realized_discontinuity(weights, set(starters) | set(REGULARS[8:])) == 0.0
    target = Fixture(TARGET, COMPETITION, SEASON, KICKOFF.date(), "home", "away")
    matches.append(Match(target, 1, 0, "a" * 64, 9, ""))
    assert xi == pytest.approx(realized_continuity(matches, rows + final)[TARGET, "home"])


def test_identity_is_not_membership():
    evidence = Evidence(CUTOFF, squads=squad("home", REGULARS[1:]) + squad("other", ["home-0"]))
    assert evidence.membership("home-0", "home").state == DEPARTED
    assert evidence.membership("home-0", "other").state == MEMBER
    lone = Evidence(CUTOFF, squads=squad("home", REGULARS[1:]))
    assert lone.membership("home-0", "home").state == UNKNOWN


def test_availability_is_scoped_to_the_team_fixture_and_representation():
    evidence = Evidence(
        CUTOFF,
        injuries=[
            injury("home-1", "away", "unavailable"),
            injury("home-1", "home", "unavailable", match_id="another-fixture"),
        ],
        fpl=[fpl("home-1", "other", "i")],
    )
    for representation in ("xi", "squad"):
        value = evidence.availability("home-1", "home", TARGET, COMPETITION, representation)[0]
        assert value == 1.0
    doubtful = Evidence(CUTOFF, injuries=[injury("home-1", "home", "doubtful")])
    assert doubtful.availability("home-1", "home", TARGET, COMPETITION, "xi")[0] == 0.1
    assert doubtful.availability("home-1", "home", TARGET, COMPETITION, "squad")[0] == 0.3


def test_new_club_availability_cannot_restore_a_former_club_player():
    rows, previous, _ = history()
    evidence = Evidence(
        CUTOFF,
        appearances=rows,
        squads=squad("home", REGULARS) + squad("other", ["home-0"]),
        transfers=[transfer("home-0", "home", "other", date(2026, 9, 10))],
        fpl=[fpl("home-0", "other", "a")],
    )
    membership = evidence.membership("home-0", "home")
    assert membership.state == DEPARTED
    assert "latest captured squad of home" in membership.conflicts
    players = expected(evidence, previous)["players"]
    player = next(row for row in players if row["player_id"] == "home-0")
    assert player["probability"] == {"xi": 0.0, "squad": 0.0}


def test_unresolved_players_cannot_create_a_large_personnel_shock():
    rows, previous, _ = history()
    evidence = Evidence(CUTOFF, appearances=rows, squads=squad("home", REGULARS[5:]))
    home = expected(evidence, previous)
    assert home["xi"]["unresolved_weight"] == pytest.approx(5 / 11)
    assert home["xi"]["d"] == pytest.approx(1 - PROPENSITY["xi"][8, True])
    assert home["xi"]["unresolved_weight"] > MAX_UNRESOLVED
    away = {"d": home["xi"]["d"], "unresolved_weight": 0.0}
    assert candidate_shift(home["xi"], away, 0.27) is None


def test_matchday_selection_is_counted_separately_from_starts():
    rows, previous, _ = history()
    kickoff = datetime(2026, 9, 5, 14, tzinfo=UTC)
    bench = [appearance(previous[-1], "home", "home-bench", kickoff, False, 20)]
    evidence = Evidence(CUTOFF, appearances=rows + bench)
    assert evidence.selection("home", previous, "home-bench") == {
        "xi": (0, False),
        "squad": (1, True),
    }
    assert set(load_propensity()) == {"xi", "squad"}


def test_equal_continuity_and_zero_kappa_leave_the_control_unchanged():
    scores = PoissonMixture(np.log([1.4, 1.1]), np.array([[0.05, 0.01], [0.01, 0.05]]))
    equal = {"d": 0.3, "unresolved_weight": 0.0}
    assert candidate_shift(equal, dict(equal), 0.27) == pytest.approx([0.0, 0.0])
    shift = candidate_shift(equal, {"d": 0.6, "unresolved_weight": 0.0}, 0.0)
    assert np.array_equal(shift, [0.0, 0.0])
    assert np.array_equal(shifted_scores(scores, shift).grid(10)[0], scores.grid(10)[0])


def test_adjustment_does_not_change_the_fitted_model(small_history):
    model = make_model({"kind": "bayesian_xg_quality_tilt"}).fit(
        small_history, small_history[-1].available_on
    )
    last = small_history[-1].fixture
    day = small_history[-1].available_on + timedelta(days=1)
    fixture = Fixture(
        f"{COMPETITION}:{last.season_id}:a:b", COMPETITION, last.season_id, day, "a", "b"
    )
    before = model.predict_match(fixture).scores
    probabilities = before.outcome_probabilities()
    shifted = shifted_scores(before, candidate_shift({"d": 0.1}, {"d": 0.5}, 0.27))
    assert shifted.outcome_probabilities() != pytest.approx(probabilities)
    assert before.outcome_probabilities() == pytest.approx(probabilities, abs=0)
    assert model.predict_match(fixture).scores.outcome_probabilities() == pytest.approx(
        probabilities, abs=0
    )


def test_personnel_evidence_ignores_market_information(tmp_path):
    request = {
        "provider": "api_football",
        "retrieved_at": BEFORE.isoformat(),
        "evidence_basis": "captured",
        "source_sha256": "a" * 64,
    }
    tables = {
        "fixtures": [
            {
                "match_id": TARGET,
                "competition_id": COMPETITION,
                "season_id": SEASON,
                "stage": "regular",
                "home_team_id": "home",
                "away_team_id": "away",
                "match_date": str(KICKOFF.date()),
                "kickoff_time": KICKOFF.isoformat(),
                "status": "scheduled",
            }
        ],
        "appearances": [
            {
                "match_id": TARGET,
                "team_id": "home",
                "player_id": p,
                "competition_id": COMPETITION,
                "season_id": SEASON,
                "kickoff_time": KICKOFF.isoformat(),
                "starts": 1,
            }
            for p in REGULARS
        ],
    }
    plain, market = tmp_path / "plain", tmp_path / "market"
    publish(plain, request, tables)
    publish(market, request, tables)
    publish(
        market,
        {**request, "provider": "football_data", "source_sha256": "b" * 64},
        {
            "odds": [
                {
                    "match_id": TARGET,
                    "competition_id": COMPETITION,
                    "season_id": SEASON,
                    "family": "closing",
                    "home_odds": 1.5,
                    "draw_odds": 4.0,
                    "away_odds": 6.0,
                }
            ]
        },
    )
    loaded = []
    for root in (plain, market):
        data = Dataset(root, CUTOFF)
        try:
            loaded.append(load_evidence(data, [SEASON]))
        finally:
            data.close()
    assert loaded[0] == loaded[1]
    assert len(loaded[0]["appearances"]) == 11
    _, spec = structural_spec(COMPETITION, tmp_path, CUTOFF)
    assert spec["kind"] == "bayesian_xg_quality_tilt"
    assert not any("market" in key for key in spec["parameters"])
