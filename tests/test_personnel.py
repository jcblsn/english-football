from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from epl_forecast.models import make_model
from epl_forecast.models.poisson import PoissonMixture
from epl_forecast.personnel import (
    DEPARTED,
    DOUBTFUL,
    HORIZON,
    KAPPA,
    MAX_UNRESOLVED,
    MEMBER,
    MIN_SUBSTITUTES,
    SQUAD_PROPENSITY,
    UNKNOWN,
    Evidence,
    dated_history,
    fixture_adjustments,
    home_log_rate_shift,
    reference_matches,
    shift_scores,
    team_continuity,
)
from epl_forecast.schema import Fixture

COMPETITION = "eng-premier-league"
SEASON = "2026-2027"
KICKOFF = datetime(2026, 9, 19, 14, tzinfo=UTC)
CUTOFF = KICKOFF - timedelta(days=3)
BEFORE = CUTOFF - timedelta(hours=2)
AFTER = CUTOFF + timedelta(hours=2)
TARGET = f"{COMPETITION}:{SEASON}:home:away"
REGULARS = [f"home-{number}" for number in range(11)]
FULL = SQUAD_PROPENSITY[8, True]


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
    rows, previous, club = [], [], []
    for index in range(8):
        match_id = f"{COMPETITION}:{SEASON}:{team}:opponent-{index}"
        kickoff = datetime(2026, 8, 1, 14, tzinfo=UTC) + timedelta(days=5 * index)
        previous.append(match_id)
        club.append((kickoff, kickoff.date(), match_id))
        rows.extend(appearance(match_id, team, f"{team}-{n}", kickoff, True, 90) for n in range(11))
    return rows, previous, club


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


def continuity(evidence, previous):
    return team_continuity(evidence, "home", TARGET, COMPETITION, previous)


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
    estimate = continuity(Evidence(CUTOFF, **base), previous)
    assert continuity(Evidence(CUTOFF, **later), previous) == estimate
    assert estimate["discontinuity"] == pytest.approx(1 - FULL)


def test_identity_is_not_membership():
    evidence = Evidence(CUTOFF, squads=squad("home", REGULARS[1:]) + squad("other", ["home-0"]))
    assert evidence.membership("home-0", "home").state == DEPARTED
    assert evidence.membership("home-0", "other").state == MEMBER
    lone = Evidence(CUTOFF, squads=squad("home", REGULARS[1:]))
    assert lone.membership("home-0", "home").state == UNKNOWN


def test_without_any_membership_capture_a_recent_player_stays_a_member():
    rows, previous, _ = history()
    evidence = Evidence(
        CUTOFF,
        appearances=rows,
        transfers=[transfer("home-0", "home", "other", date(2026, 9, 10))],
    )
    assert evidence.membership("home-1", "home").state == MEMBER
    assert evidence.membership("home-0", "home").state == DEPARTED
    estimate = continuity(evidence, previous)
    assert estimate["unresolved_weight"] == 0
    assert estimate["discontinuity"] == pytest.approx(1 - FULL * 10 / 11)


def test_availability_is_scoped_to_the_team_and_fixture():
    evidence = Evidence(
        CUTOFF,
        injuries=[
            injury("home-1", "away", "unavailable"),
            injury("home-1", "home", "unavailable", match_id="another-fixture"),
        ],
        fpl=[fpl("home-1", "other", "i")],
    )
    assert evidence.availability("home-1", "home", TARGET, COMPETITION)[0] == 1.0
    doubtful = Evidence(CUTOFF, injuries=[injury("home-1", "home", "doubtful")])
    assert doubtful.availability("home-1", "home", TARGET, COMPETITION)[0] == DOUBTFUL
    conflict = Evidence(
        CUTOFF, injuries=[injury("home-1", "home", "unavailable")], fpl=[fpl("home-1", "home", "a")]
    )
    assert conflict.availability("home-1", "home", TARGET, COMPETITION)[0] is None


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
    player = next(
        p for p in continuity(evidence, previous)["players"] if p["player_id"] == "home-0"
    )
    assert player["probability"] == 0.0


def test_unresolved_players_cannot_create_a_large_personnel_shock():
    rows, previous, _ = history()
    home = continuity(
        Evidence(CUTOFF, appearances=rows, squads=squad("home", REGULARS[5:])), previous
    )
    assert home["unresolved_weight"] == pytest.approx(5 / 11)
    assert home["unresolved_weight"] > MAX_UNRESOLVED
    assert home["discontinuity"] == pytest.approx(1 - FULL)
    away = {"discontinuity": 0.0, "unresolved_weight": 0.0}
    assert home_log_rate_shift(home, away) is None
    assert home_log_rate_shift(away, {"discontinuity": 0.2, "unresolved_weight": 0.0}) == (
        pytest.approx(KAPPA * 0.2)
    )


def test_an_official_team_sheet_before_the_cutoff_makes_the_feature_observed():
    rows, previous, _ = history()
    sheet_time = KICKOFF - timedelta(minutes=60)
    starters = REGULARS[:9] + ["new-1", "new-2"]
    bench = ["home-9"] + [f"bench-{n}" for n in range(MIN_SUBSTITUTES - 1)]
    sheet = [appearance(TARGET, "home", p, KICKOFF, True, None, sheet_time) for p in starters] + [
        appearance(TARGET, "home", p, KICKOFF, False, None, sheet_time) for p in bench
    ]
    base = {"appearances": rows + sheet, "squads": squad("home", REGULARS)}
    observed = continuity(Evidence(KICKOFF - timedelta(minutes=30), **base), previous)
    assert observed["team_sheet_retrieved_at"] == sheet_time.isoformat()
    assert observed["discontinuity"] == pytest.approx(1 / 11)
    before = continuity(Evidence(KICKOFF - timedelta(minutes=90), **base), previous)
    assert before["team_sheet_retrieved_at"] is None
    late = [{**row, "retrieved_at": KICKOFF + timedelta(minutes=5)} for row in sheet]
    assert (
        Evidence(KICKOFF + timedelta(hours=1), appearances=rows + late).team_sheet(TARGET, "home")
        is None
    )


def test_a_team_sheet_without_the_whole_matchday_squad_is_not_observed():
    rows, previous, _ = history()
    sheet_time = KICKOFF - timedelta(minutes=60)
    partial = [appearance(TARGET, "home", p, KICKOFF, True, None, sheet_time) for p in REGULARS] + [
        appearance(TARGET, "home", f"bench-{n}", KICKOFF, False, None, sheet_time)
        for n in range(MIN_SUBSTITUTES - 1)
    ]
    evidence = Evidence(
        KICKOFF - timedelta(minutes=30), appearances=rows + partial, squads=squad("home", REGULARS)
    )
    assert evidence.team_sheet(TARGET, "home") is None
    assert continuity(evidence, previous)["discontinuity"] == pytest.approx(1 - FULL)
    earlier = sheet_time - timedelta(minutes=10)
    complete = [appearance(TARGET, "home", p, KICKOFF, True, None, earlier) for p in REGULARS] + [
        appearance(TARGET, "home", f"bench-{n}", KICKOFF, False, None, earlier)
        for n in range(MIN_SUBSTITUTES)
    ]
    evidence = Evidence(KICKOFF - timedelta(minutes=30), appearances=rows + complete + partial)
    assert evidence.team_sheet(TARGET, "home")[1] == earlier


def test_reference_matches_are_the_matches_known_at_the_cutoff():
    rows, previous, club = history()
    wednesday = datetime(2026, 9, 16, 19, tzinfo=UTC)
    midweek = f"{COMPETITION}:{SEASON}:home:midweek"
    rows = rows + [appearance(midweek, "home", p, wednesday, True, 90) for p in REGULARS]
    club = [*club, (wednesday, wednesday.date(), midweek)]
    six_days = KICKOFF - timedelta(days=6)
    early = reference_matches(club, KICKOFF.date(), six_days)
    assert early == previous
    assert Evidence(six_days, appearances=rows).recent_weights("home", early) is not None
    late = reference_matches(club, KICKOFF.date(), KICKOFF - timedelta(minutes=90))
    assert late == [*previous, midweek]


def test_only_near_fixtures_in_the_two_divisions_get_a_record():
    rows, _, club = history()
    away_rows, _, away_club = history("away")
    evidence = Evidence(CUTOFF, appearances=rows + away_rows)
    histories = {"home": club, "away": away_club}
    near = Fixture(TARGET, COMPETITION, SEASON, KICKOFF.date(), "home", "away")
    far_kickoff = CUTOFF + HORIZON + timedelta(minutes=1)
    far = Fixture(
        f"{COMPETITION}:{SEASON}:away:home", COMPETITION, SEASON, far_kickoff.date(), "away", "home"
    )
    lower_id = f"eng-league-one:{SEASON}:home:away"
    lower = Fixture(lower_id, "eng-league-one", SEASON, KICKOFF.date(), "home", "away")
    kickoffs = {TARGET: KICKOFF, far.match_id: far_kickoff, lower_id: KICKOFF}
    records = fixture_adjustments(evidence, histories, [near, far, lower], kickoffs, CUTOFF)
    assert set(records) == {TARGET}
    assert records[TARGET]["home_log_rate_shift"] == pytest.approx(0.0)


def test_history_dates_a_matchday_squad_from_the_day_after_its_match():
    rows, previous, _ = history()
    dated = dated_history(rows, [transfer("home-0", "home", "other", date(2026, 9, 10))])
    last = datetime(2026, 9, 5, 14, tzinfo=UTC)
    assert Evidence(last + timedelta(hours=3), **dated).recent_weights("home", previous) is None
    evidence = Evidence(CUTOFF, **dated)
    assert evidence.recent_weights("home", previous) is not None
    assert evidence.membership("home-0", "home").state == DEPARTED
    assert evidence.membership("home-1", "home").state == MEMBER


def test_a_zero_shift_leaves_the_score_distribution_unchanged():
    scores = PoissonMixture(np.log([1.4, 1.1]), np.array([[0.05, 0.01], [0.01, 0.05]]))
    assert np.array_equal(shift_scores(scores, 0.0).grid(10)[0], scores.grid(10)[0])
    shifted = shift_scores(scores, 0.2)
    assert shifted.home_rate == pytest.approx(scores.home_rate * np.exp(0.2))
    assert shifted.away_rate == pytest.approx(scores.away_rate * np.exp(-0.2))
    assert scores.home_rate == pytest.approx(float(scores.weights @ scores.home_rates))


def test_a_shift_moves_one_fixture_without_changing_the_model_or_its_states(small_history):
    model = make_model({"kind": "bayesian_xg_quality_tilt"}).fit(
        small_history, small_history[-1].available_on
    )
    last = small_history[-1].fixture
    day = small_history[-1].available_on + timedelta(days=1)
    fixture = Fixture(
        f"{COMPETITION}:{last.season_id}:a:b", COMPETITION, last.season_id, day, "a", "b"
    )
    before = model.predict_match(fixture).scores.outcome_probabilities()
    shifted = shift_scores(model.predict_match(fixture).scores, 0.2)
    assert shifted.outcome_probabilities()[0] > before[0]
    assert model.predict_match(fixture).scores.outcome_probabilities() == pytest.approx(
        before, abs=0
    )
    plain = model.sample_forecast_state(np.random.default_rng(1), 40000)
    moved = model.sample_forecast_state(np.random.default_rng(1), 40000)
    home, away = plain.sample_scores(fixture, np.random.default_rng(2))
    shifted_home, shifted_away = moved.sample_scores(
        fixture, np.random.default_rng(2), log_rate_shift=0.2
    )
    assert shifted_home.mean() / home.mean() == pytest.approx(np.exp(0.2), rel=0.03)
    assert shifted_away.mean() / away.mean() == pytest.approx(np.exp(-0.2), rel=0.03)
    later = Fixture(
        f"{COMPETITION}:{last.season_id}:b:a", COMPETITION, last.season_id, day, "b", "a"
    )
    assert np.array_equal(plain.rates(later)[0], moved.rates(later)[0])
