from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from epl_forecast.models import make_model
from epl_forecast.models.poisson import PoissonMixture
from epl_forecast.models.quality_tilt_scores import shift_scores
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
    team_continuity,
)
from epl_forecast.schema import Fixture
from epl_forecast.snapshots import (
    FPL_AVAILABILITY,
    INJURIES,
    SQUAD,
    capture_of,
    injury_scope,
    snapshot,
)

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


def fpl(player, team, status, retrieved_at=BEFORE, season=SEASON):
    return {
        "player_id": player,
        "team_id": team,
        "season_id": season,
        "status": status,
        "reason": "",
        "retrieved_at": retrieved_at,
    }


def injury(player, team, status, match_id=TARGET, retrieved_at=BEFORE, season=SEASON):
    return {
        "match_id": match_id,
        "team_id": team,
        "player_id": player,
        "competition_id": COMPETITION,
        "season_id": season,
        "status": status,
        "reason": "Injury",
        "retrieved_at": retrieved_at,
    }


def source_snapshot(kind, key, retrieved_at, row_count=1):
    return {
        **snapshot(kind, key, endpoint="test", row_count=row_count),
        "retrieved_at": retrieved_at,
        "source_sha256": "",
    }


def derive_snapshots(squads=(), injuries=(), fpl_rows=()):
    """The snapshot rows that a collection records beside these observations.

    A test that wants a scope the provider answered with no rows passes its own snapshots.
    """
    scopes = {}
    for row in squads:
        scopes.setdefault((SQUAD, row["team_id"]), []).append(capture_of(row))
    for row in injuries:
        key = INJURIES, injury_scope(row["competition_id"], row["season_id"])
        scopes.setdefault(key, []).append(capture_of(row))
    for row in fpl_rows:
        scopes.setdefault((FPL_AVAILABILITY, row["season_id"]), []).append(capture_of(row))
    return [
        source_snapshot(kind, key, max(captures)[0], len(captures))
        for (kind, key), captures in scopes.items()
    ]


def evidence_at(cutoff, *, snapshots=None, **rows):
    """Evidence together with the snapshots that its observations imply."""
    if snapshots is None:
        snapshots = derive_snapshots(
            rows.get("squads", ()), rows.get("injuries", ()), rows.get("fpl", ())
        )
    return Evidence(cutoff, **rows, snapshots=snapshots)


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
    estimate = continuity(evidence_at(CUTOFF, **base), previous)
    assert continuity(evidence_at(CUTOFF, **later), previous) == estimate
    assert estimate["discontinuity"] == pytest.approx(1 - FULL)


def test_identity_is_not_membership():
    evidence = evidence_at(CUTOFF, squads=squad("home", REGULARS[1:]) + squad("other", ["home-0"]))
    assert evidence.membership("home-0", "home").state == DEPARTED
    assert evidence.membership("home-0", "other").state == MEMBER
    lone = evidence_at(CUTOFF, squads=squad("home", REGULARS[1:]))
    assert lone.membership("home-0", "home").state == UNKNOWN


def test_without_any_membership_capture_a_recent_player_stays_a_member():
    rows, previous, _ = history()
    evidence = evidence_at(
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
    evidence = evidence_at(
        CUTOFF,
        injuries=[
            injury("home-1", "away", "unavailable"),
            injury("home-1", "home", "unavailable", match_id="another-fixture"),
        ],
        fpl=[fpl("home-1", "other", "i")],
    )
    assert evidence.availability("home-1", "home", TARGET, COMPETITION)[0] == 1.0
    doubtful = evidence_at(CUTOFF, injuries=[injury("home-1", "home", "doubtful")])
    assert doubtful.availability("home-1", "home", TARGET, COMPETITION)[0] == DOUBTFUL
    conflict = evidence_at(
        CUTOFF, injuries=[injury("home-1", "home", "unavailable")], fpl=[fpl("home-1", "home", "a")]
    )
    assert conflict.availability("home-1", "home", TARGET, COMPETITION)[0] is None


def test_new_club_availability_cannot_restore_a_former_club_player():
    rows, previous, _ = history()
    evidence = evidence_at(
        CUTOFF,
        appearances=rows,
        squads=squad("home", REGULARS) + squad("other", ["home-0"]),
        transfers=[transfer("home-0", "home", "other", date(2026, 9, 10))],
        fpl=[fpl("home-0", "other", "a")],
    )
    membership = evidence.membership("home-0", "home")
    assert membership.state == DEPARTED
    assert "latest squad snapshot of home" in membership.conflicts
    player = next(
        p for p in continuity(evidence, previous)["players"] if p["player_id"] == "home-0"
    )
    assert player["probability"] == 0.0


def test_unresolved_players_cannot_create_a_large_personnel_shock():
    rows, previous, _ = history()
    home = continuity(
        evidence_at(CUTOFF, appearances=rows, squads=squad("home", REGULARS[5:])), previous
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
    observed = continuity(evidence_at(KICKOFF - timedelta(minutes=30), **base), previous)
    assert observed["team_sheet_retrieved_at"] == sheet_time.isoformat()
    assert observed["discontinuity"] == pytest.approx(1 / 11)
    before = continuity(evidence_at(KICKOFF - timedelta(minutes=90), **base), previous)
    assert before["team_sheet_retrieved_at"] is None
    late = [{**row, "retrieved_at": KICKOFF + timedelta(minutes=5)} for row in sheet]
    assert (
        evidence_at(KICKOFF + timedelta(hours=1), appearances=rows + late).team_sheet(
            TARGET, "home"
        )
        is None
    )


def test_a_team_sheet_without_the_whole_matchday_squad_is_not_observed():
    rows, previous, _ = history()
    sheet_time = KICKOFF - timedelta(minutes=60)
    partial = [appearance(TARGET, "home", p, KICKOFF, True, None, sheet_time) for p in REGULARS] + [
        appearance(TARGET, "home", f"bench-{n}", KICKOFF, False, None, sheet_time)
        for n in range(MIN_SUBSTITUTES - 1)
    ]
    evidence = evidence_at(
        KICKOFF - timedelta(minutes=30), appearances=rows + partial, squads=squad("home", REGULARS)
    )
    assert evidence.team_sheet(TARGET, "home") is None
    assert continuity(evidence, previous)["discontinuity"] == pytest.approx(1 - FULL)
    earlier = sheet_time - timedelta(minutes=10)
    complete = [appearance(TARGET, "home", p, KICKOFF, True, None, earlier) for p in REGULARS] + [
        appearance(TARGET, "home", f"bench-{n}", KICKOFF, False, None, earlier)
        for n in range(MIN_SUBSTITUTES)
    ]
    evidence = evidence_at(KICKOFF - timedelta(minutes=30), appearances=rows + complete + partial)
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
    assert evidence_at(six_days, appearances=rows).recent_weights("home", early) is not None
    late = reference_matches(club, KICKOFF.date(), KICKOFF - timedelta(minutes=90))
    assert late == [*previous, midweek]


def test_only_near_fixtures_in_the_two_divisions_get_a_record():
    rows, _, club = history()
    away_rows, _, away_club = history("away")
    evidence = evidence_at(CUTOFF, appearances=rows + away_rows)
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
    assert evidence_at(last + timedelta(hours=3), **dated).recent_weights("home", previous) is None
    evidence = evidence_at(CUTOFF, **dated)
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


def test_a_later_squad_snapshot_with_no_rows_empties_the_scope():
    rows, previous, _ = history()
    squads = squad("home", REGULARS)
    # The provider answered the squad request with nobody. That is an observation, not
    # silence, so the squad it replaces may not stay in force.
    empty = source_snapshot(SQUAD, "home", CUTOFF - timedelta(hours=1), row_count=0)
    evidence = evidence_at(
        CUTOFF,
        appearances=rows,
        squads=squads,
        snapshots=[*derive_snapshots(squads), empty],
    )
    assert evidence.squads["home"] == set()
    assert evidence.membership("home-1", "home").state == UNKNOWN
    assert continuity(evidence, previous)["unresolved_weight"] == pytest.approx(1.0)


def test_a_later_injury_snapshot_with_no_rows_clears_the_earlier_list():
    listed = [injury("home-1", "home", "unavailable")]
    assert (
        evidence_at(CUTOFF, injuries=listed).availability("home-1", "home", TARGET, COMPETITION)[0]
        == 0.0
    )
    cleared = source_snapshot(
        INJURIES, injury_scope(COMPETITION, SEASON), CUTOFF - timedelta(hours=1), row_count=0
    )
    evidence = evidence_at(
        CUTOFF, injuries=listed, snapshots=[*derive_snapshots(injuries=listed), cleared]
    )
    assert evidence.availability("home-1", "home", TARGET, COMPETITION)[0] == 1.0
    assert TARGET not in evidence.injury_fixtures


def test_a_later_response_for_an_earlier_season_does_not_supersede_this_season():
    current = [injury("home-1", "home", "unavailable")]
    # The same competition and a later retrieval, but the season before this one. Selecting
    # the latest row of the competition would drop the current-season evidence.
    earlier_season = [
        injury(
            "home-2",
            "home",
            "unavailable",
            retrieved_at=CUTOFF - timedelta(minutes=1),
            season="2025-2026",
        )
    ]
    evidence = evidence_at(CUTOFF, injuries=current + earlier_season)
    assert evidence.availability("home-1", "home", TARGET, COMPETITION)[0] == 0.0


def test_the_estimate_does_not_depend_on_the_order_the_rows_arrive_in():
    rows, previous, _ = history()
    squads = squad("home", REGULARS)
    injuries = [injury("home-1", "home", "doubtful")]
    statuses = [fpl("home-2", "home", "d")]
    snapshots = derive_snapshots(squads, injuries, statuses)
    forward = evidence_at(
        CUTOFF,
        appearances=rows,
        squads=squads,
        injuries=injuries,
        fpl=statuses,
        snapshots=snapshots,
    )
    backward = evidence_at(
        CUTOFF,
        appearances=rows[::-1],
        squads=squads[::-1],
        injuries=injuries[::-1],
        fpl=statuses[::-1],
        snapshots=snapshots[::-1],
    )
    assert continuity(backward, previous) == continuity(forward, previous)


def test_a_corrected_capture_replaces_the_one_it_corrects():
    rows, previous, _ = history()
    corrected_match = previous[0]
    kickoff = datetime(2026, 8, 1, 14, tzinfo=UTC)
    later = kickoff + timedelta(days=2)
    # The provider re-reports the match without one player who it first said had played.
    without = [
        appearance(corrected_match, "home", f"home-{n}", kickoff, True, 90, later)
        for n in range(10)
    ]
    removed = evidence_at(CUTOFF, appearances=rows + without, squads=squad("home", REGULARS))
    assert "home-10" not in removed.matchday[corrected_match, "home"]
    assert removed.recent_weights("home", previous)["home-10"] == 7 * 90
    assert removed.recent_weights("home", previous)["home-0"] == 8 * 90
    assert removed.selection("home", previous, "home-10") == (7, True)
    # A correction to the minutes of one player replaces them rather than overwriting them
    # in whichever order the rows happen to be read.
    fewer_minutes = [
        *without,
        appearance(corrected_match, "home", "home-10", kickoff, True, 20, later),
    ]
    changed = evidence_at(CUTOFF, appearances=rows + fewer_minutes, squads=squad("home", REGULARS))
    assert changed.recent_weights("home", previous)["home-10"] == 7 * 90 + 20


def test_a_later_capture_without_minutes_cannot_erase_a_complete_one():
    rows, previous, _ = history()
    corrected_match = previous[0]
    kickoff = datetime(2026, 8, 1, 14, tzinfo=UTC)
    # A short response for a finished match is not a correction; it records no minutes.
    unusable = [
        appearance(corrected_match, "home", p, kickoff, True, None, kickoff + timedelta(days=2))
        for p in REGULARS
    ]
    evidence = evidence_at(CUTOFF, appearances=rows + unusable, squads=squad("home", REGULARS))
    assert evidence.recent_weights("home", previous)["home-0"] == 8 * 90


def test_a_completed_match_without_a_usable_capture_has_no_participants():
    match_id = f"{COMPETITION}:{SEASON}:home:opponent"
    kickoff = datetime(2026, 8, 1, 14, tzinfo=UTC)
    rows = [appearance(match_id, "home", player, kickoff, True, None) for player in REGULARS]
    evidence = evidence_at(CUTOFF, appearances=rows)
    assert evidence.matchday[match_id, "home"] == set()
    assert evidence.spells == {}


def test_contradictory_strong_evidence_of_the_same_day_leaves_membership_unknown():
    day = date(2026, 9, 10)
    transfers = [
        transfer("home-0", "home", "other", day),
        transfer("home-0", "other", "home", day),
    ]
    both_ways = evidence_at(
        CUTOFF,
        transfers=transfers,
    )
    membership = both_ways.membership("home-0", "home")
    assert membership.state == UNKNOWN
    reversed_evidence = evidence_at(CUTOFF, transfers=list(reversed(transfers)))
    assert reversed_evidence.membership("home-0", "home") == membership
    dated = evidence_at(
        CUTOFF,
        transfers=[
            transfer("home-0", "home", "other", day),
            transfer("home-0", "other", "home", day + timedelta(days=1)),
        ],
    )
    assert dated.membership("home-0", "home").state == MEMBER


def test_a_snapshot_retrieved_after_the_cutoff_has_no_effect():
    rows, previous, _ = history()
    squads = squad("home", REGULARS)
    baseline = evidence_at(CUTOFF, appearances=rows, squads=squads)
    later = evidence_at(
        CUTOFF,
        appearances=rows,
        squads=squads,
        snapshots=[*derive_snapshots(squads), source_snapshot(SQUAD, "home", AFTER, row_count=0)],
    )
    assert continuity(later, previous) == continuity(baseline, previous)
