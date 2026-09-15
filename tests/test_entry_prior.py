from datetime import date, timedelta

import numpy as np
import pytest

from epl_forecast.models.entry_prior import (
    EntryPriorModel,
    club_features,
    entry_panel,
    memory_weight,
    transition_id,
)
from epl_forecast.models.promotion import CHAMPIONSHIP, PL, completed_seasons
from epl_forecast.models.quality_tilt import QualityTiltFilter
from epl_forecast.schema import Fixture, Match, fixture_id

BASE, HOME, LEVEL = np.log(1.35), 0.24, -0.15
LEAGUE_TWO = "eng-league-two"
NATIONAL_LEAGUE = "eng-national-league"


def play(rng, competition, season, teams, quality, offset, start):
    matches = []
    pairs = [(h, a) for h in teams for a in teams if h != a]
    per_day = len(teams) // 2
    for index, (home, away) in enumerate(pairs):
        day = start + timedelta(days=7 * (index // per_day))
        fixture = Fixture(
            fixture_id(competition, season, home, away), competition, season, day, home, away
        )
        home_rate = np.exp(BASE + HOME + offset + quality[home] - quality[away])
        away_rate = np.exp(BASE + offset + quality[away] - quality[home])
        matches.append(Match(fixture, int(rng.poisson(home_rate)), int(rng.poisson(away_rate))))
    return matches


def two_division_history(seed=5, seasons=7):
    """Full-size divisions with promotion, relegation and clubs arriving from outside."""
    rng = np.random.default_rng(seed)
    quality = {}
    premier = [f"pl{i}" for i in range(20)]
    championship = [f"ch{i}" for i in range(24)]
    reserve = [f"lo{i}" for i in range(12)]
    for team in premier:
        quality[team] = rng.normal(0.25, 0.16)
    for team in championship + reserve:
        quality[team] = rng.normal(-0.10, 0.16)
    matches = []
    for year in range(2012, 2012 + seasons):
        season = f"{year}-{year + 1}"
        divisions = {}
        for competition, teams, offset in (
            (PL, premier, 0.0),
            (CHAMPIONSHIP, championship, LEVEL),
        ):
            games = play(rng, competition, season, teams, quality, offset, date(year, 8, 1))
            matches.extend(games)
            points = dict.fromkeys(teams, 0)
            for match in games:
                home, away = match.fixture.home_team_id, match.fixture.away_team_id
                points[home] += 3 * (match.home_goals > match.away_goals) + (
                    match.home_goals == match.away_goals
                )
                points[away] += 3 * (match.away_goals > match.home_goals) + (
                    match.home_goals == match.away_goals
                )
            divisions[competition] = sorted(teams, key=lambda t: -points[t])
        premier, championship = divisions[PL], divisions[CHAMPIONSHIP]
        down, up = premier[-3:], championship[:3]
        premier = premier[:-3] + up
        championship = championship[3:-3] + down + reserve[:3]
        reserve = reserve[3:] + divisions[CHAMPIONSHIP][-3:]
    return matches


def panel(matches, as_of=date(2030, 1, 1)):
    return completed_seasons(matches, as_of)


def national_league_history(seed=9):
    rng = np.random.default_rng(seed)
    league_two = [f"league-two-{index}" for index in range(24)]
    national = [f"national-{index}" for index in range(24)]
    quality = {team: rng.normal(0, 0.15) for team in [*league_two, *national]}
    previous = "2024-2025"
    matches = [
        *play(rng, LEAGUE_TWO, previous, league_two, quality, 0, date(2024, 8, 1)),
        *play(rng, NATIONAL_LEAGUE, previous, national, quality, -0.15, date(2024, 8, 1)),
    ]
    target = "2025-2026"
    target_teams = [*league_two[:-2], *national[:2]]
    matches.extend(
        play(rng, LEAGUE_TWO, target, target_teams, quality, 0, date(2025, 8, 1))[:1]
    )
    return matches, target, national[:2]


def test_memory_weight_decays_and_rejects_a_continuing_club():
    assert memory_weight(2, 4.0) == pytest.approx(1.0)
    assert memory_weight(6, 4.0) < memory_weight(3, 4.0) < 1.0
    assert memory_weight(12, np.inf) == 1.0
    with pytest.raises(ValueError, match="at least two years"):
        memory_weight(1, 4.0)


def test_features_separate_continuing_clubs_from_each_kind_of_entrant():
    seasons = panel(two_division_history())
    target = sorted({s for (c, s) in seasons if c == CHAMPIONSHIP})[-1]
    rows = entry_panel(tuple(sorted(seasons.items())), CHAMPIONSHIP)
    assert {r["transition"] for r in rows} == {
        transition_id(PL, CHAMPIONSHIP),
        transition_id(None, CHAMPIONSHIP),
    }
    for row in rows:
        if row["source_competition"] is None:
            assert row["source_attack"] is None
        else:
            assert row["source_attack"] is not None
        assert row["memory_age"] is None or row["memory_age"] >= 2
    continuing = [
        team
        for team in sorted({m.fixture.home_team_id for m in seasons[CHAMPIONSHIP, target]})
        if club_features(seasons, CHAMPIONSHIP, target, team) is None
    ]
    assert len(continuing) == 24 - sum(r["season_id"] == target for r in rows)


def test_a_national_league_source_season_prevents_the_outside_fallback():
    matches, target, entrants = national_league_history()
    seasons = completed_seasons(matches, date(2025, 8, 2))
    assert (NATIONAL_LEAGUE, "2024-2025") in seasons
    for team in entrants:
        features = club_features(seasons, LEAGUE_TWO, target, team)
        assert features["transition"] == transition_id(NATIONAL_LEAGUE, LEAGUE_TWO)
        assert features["source_attack"] is not None
        without_source = {key: rows for key, rows in seasons.items() if key[0] != NATIONAL_LEAGUE}
        fallback = club_features(without_source, LEAGUE_TWO, target, team)
        assert fallback["transition"] == transition_id(None, LEAGUE_TWO)
        assert fallback["source_attack"] is None


def test_national_league_matches_do_not_update_the_league_two_filter():
    matches, target, entrants = national_league_history()
    cutoff = date(2025, 8, 2)
    eligible = [match for match in matches if match.available_on <= cutoff]
    model = QualityTiltFilter()
    model.primary_competition = LEAGUE_TWO
    model.fit(eligible, cutoff)
    league_two_dates = {
        match.fixture.match_date
        for match in eligible
        if match.fixture.competition_id == LEAGUE_TWO
    }
    assert model.updates == len(league_two_dates)
    assert not (set(model.team_index) & {f"national-{index}" for index in range(2, 24)})
    for team in entrants:
        assert model.team_state(team, target).source.startswith(
            transition_id(NATIONAL_LEAGUE, LEAGUE_TWO)
        )


def test_the_transition_prior_separates_relegated_clubs_from_outside_arrivals():
    seasons = panel(two_division_history())
    target = sorted({s for (c, s) in seasons if c == CHAMPIONSHIP})[-1]
    model = EntryPriorModel(seasons, CHAMPIONSHIP, target, date(2030, 1, 1), "transition")
    priors = {}
    for team in sorted({m.fixture.home_team_id for m in seasons[CHAMPIONSHIP, target]}):
        features = club_features(seasons, CHAMPIONSHIP, target, team)
        if features is not None:
            priors[features["transition"]] = model.prior(team)
    relegated = priors[transition_id(PL, CHAMPIONSHIP)]
    outside = priors[transition_id(None, CHAMPIONSHIP)]
    assert relegated.mean[0] > outside.mean[0]
    for prior in (relegated, outside):
        assert np.linalg.eigvalsh(prior.covariance).min() > 0


def test_a_continuing_club_has_no_entry_prior_and_population_stays_flat():
    seasons = panel(two_division_history())
    target = sorted({s for (c, s) in seasons if c == CHAMPIONSHIP})[-1]
    teams = sorted({m.fixture.home_team_id for m in seasons[CHAMPIONSHIP, target]})
    flat = EntryPriorModel(seasons, CHAMPIONSHIP, target, date(2030, 1, 1), "population")
    continuing = [t for t in teams if flat.prior(t) is None]
    entering = [t for t in teams if flat.prior(t) is not None]
    assert continuing and entering
    for team in entering:
        np.testing.assert_allclose(flat.prior(team).mean, np.zeros(2))
        np.testing.assert_allclose(flat.prior(team).covariance, np.eye(2) * 0.4**2)


def test_entry_priors_use_only_transitions_that_finished_before_the_cutoff():
    matches = two_division_history()
    seasons = panel(matches)
    ordered = sorted({s for (c, s) in seasons if c == CHAMPIONSHIP})
    target = ordered[-2]
    teams = sorted({m.fixture.home_team_id for m in seasons[CHAMPIONSHIP, target]})
    left = EntryPriorModel(seasons, CHAMPIONSHIP, target, date(2030, 1, 1), "memory")
    altered = {
        key: tuple(Match(m.fixture, m.home_goals + 6, m.away_goals) for m in rows)
        if key[1] >= target
        else rows
        for key, rows in seasons.items()
    }
    right = EntryPriorModel(altered, CHAMPIONSHIP, target, date(2030, 1, 1), "memory")
    assert max(r["season_id"] for r in left.rows) == ordered[-3]
    entering = [t for t in teams if left.prior(t) is not None]
    assert entering
    for team in entering:
        np.testing.assert_array_equal(left.prior(team).mean, right.prior(team).mean)
        np.testing.assert_array_equal(left.prior(team).covariance, right.prior(team).covariance)
    mid = max(m.fixture.match_date for m in seasons[CHAMPIONSHIP, ordered[-3]])
    early = EntryPriorModel(seasons, CHAMPIONSHIP, target, mid, "memory")
    assert max(r["season_id"] for r in early.rows) == ordered[-4]


def test_an_unknown_level_or_division_is_refused():
    seasons = panel(two_division_history())
    target = sorted({s for (c, s) in seasons if c == CHAMPIONSHIP})[-1]
    with pytest.raises(ValueError, match="level"):
        EntryPriorModel(seasons, CHAMPIONSHIP, target, date(2030, 1, 1), "hunch")
    with pytest.raises(ValueError, match="modeled divisions"):
        EntryPriorModel(seasons, "eng-national-league", target, date(2030, 1, 1), "transition")
    with pytest.raises(ValueError, match="training label"):
        EntryPriorModel(seasons, CHAMPIONSHIP, target, date(2030, 1, 1), "memory", label="vibes")


def test_the_filter_replaces_an_entering_state_and_keeps_a_continuing_one():
    matches = two_division_history()
    seasons = panel(matches)
    target = sorted({s for (c, s) in seasons if c == CHAMPIONSHIP})[-1]
    cutoff = min(m.fixture.match_date for m in seasons[CHAMPIONSHIP, target])
    training = [m for m in matches if m.available_on <= cutoff]
    model = QualityTiltFilter()
    model.primary_competition = CHAMPIONSHIP
    model.entry_prior = "source"
    model.fit(training, cutoff)
    sources = {}
    for team in sorted({m.fixture.home_team_id for m in seasons[CHAMPIONSHIP, target]}):
        sources[team] = model.team_state(team, target).source
    entering = [t for t, s in sources.items() if s.endswith("entry prior")]
    continuing = [t for t, s in sources.items() if s == "previous league state"]
    assert len(entering) == 6
    assert len(continuing) == 18
    for team in entering:
        assert club_features(seasons, CHAMPIONSHIP, target, team) is not None


def test_the_generic_rule_is_the_default_and_can_be_switched_off():
    matches = two_division_history()
    seasons = panel(matches)
    target = sorted({s for (c, s) in seasons if c == CHAMPIONSHIP})[-1]
    cutoff = min(m.fixture.match_date for m in seasons[CHAMPIONSHIP, target])
    training = [m for m in matches if m.available_on <= cutoff]
    default = QualityTiltFilter()
    default.primary_competition = CHAMPIONSHIP
    assert default.entry_prior == "memory"
    default.fit(training, cutoff)
    teams = sorted({m.fixture.home_team_id for m in seasons[CHAMPIONSHIP, target]})
    assert any(default.team_state(t, target).source.endswith("entry prior") for t in teams)
    retained = QualityTiltFilter()
    retained.primary_competition = CHAMPIONSHIP
    retained.entry_prior = None
    retained.fit(training, cutoff)
    sources = {retained.team_state(team, target).source for team in teams}
    assert sources <= {"previous league state", "league population"}
