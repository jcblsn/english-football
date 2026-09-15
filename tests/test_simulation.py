from dataclasses import replace
from datetime import date

import numpy as np
import pytest

from epl_forecast.cli import fitted_model
from epl_forecast.data.rules import league_rules, reviewed_rules_evidence
from epl_forecast.models.base import Forecast
from epl_forecast.postseason import simulate_playoffs
from epl_forecast.sanctions import reviewed_adjustments
from epl_forecast.simulation import (
    EuropeScenario,
    european_places,
    rank_table,
    simulate_season,
    validate_schedule,
)


def test_reviewed_efl_edition_matches_current_boundaries_only():
    evidence = reviewed_rules_evidence("eng-championship", "2026-2027")
    rules = league_rules("eng-championship", "2026-2027")
    assert evidence["edition"] == "EFL Regulations 2026/27"
    assert evidence["automatic_promotion"] == rules.automatic_promotion == 2
    assert evidence["playoff_end"] == rules.playoff_end == 8
    assert evidence["relegated"] == rules.relegated == 3
    assert reviewed_rules_evidence("eng-championship", "2027-2028") is None
    assert reviewed_rules_evidence("eng-premier-league", "2026-2027") is None


class FixedHomeWin:
    def sample(self, rng, size):
        return np.ones(size, dtype=int), np.zeros(size, dtype=int)


class FixedModel:
    def __init__(self, as_of):
        self.as_of = as_of

    def predict_match(self, fixture):
        return Forecast((1.0, 0.0, 0.0), FixedHomeWin())


def test_schedule_rejects_missing_duplicate_and_future_results(full_season):
    teams = sorted({m.fixture.home_team_id for m in full_season})
    cutoff = date(2020, 8, 10)
    played = [m for m in full_season if m.available_on <= cutoff]
    remaining = [m.fixture for m in full_season if m.available_on > cutoff]
    validate_schedule(teams, played, remaining, cutoff)
    for bad in (remaining[:-1], remaining[:-1] + [remaining[0]]):
        with pytest.raises(ValueError, match="every ordered"):
            validate_schedule(teams, played, bad, cutoff)
    with pytest.raises(ValueError, match="available"):
        validate_schedule(teams, full_season, [], cutoff)


def test_fixed_remainder_conserves_probabilities_and_scores(full_season):
    teams = sorted({m.fixture.home_team_id for m in full_season})
    cutoff = date(2020, 8, 10)
    played = [m for m in full_season if m.available_on <= cutoff]
    remaining = [m.fixture for m in full_season if m.available_on > cutoff]
    result = simulate_season(FixedModel(cutoff), played, remaining, teams, cutoff, 8, 101)
    repeat = simulate_season(FixedModel(cutoff), played, remaining, teams, cutoff, 8, 101)
    assert result == repeat
    assert result["played_matches"] == 90
    assert result["remaining_matches"] == 290
    assert result["unresolved_decisive_tie_rate"] == 1
    for row in result["teams"]:
        assert row["points_distribution"] == {"57": 1.0}
        assert row["goal_difference_distribution"] == {"0": 1.0}
        assert row["position_probabilities"] == pytest.approx([0.05] * 20)
        assert row["title_probability"] == pytest.approx(0.05)
        assert row["relegation_probability"] == pytest.approx(0.15)
    assert sum(r["title_probability"] for r in result["teams"]) == pytest.approx(1)
    assert sum(r["relegation_probability"] for r in result["teams"]) == pytest.approx(3)


def test_played_scores_are_fixed_and_only_known_deductions_apply(full_season):
    teams = sorted({m.fixture.home_team_id for m in full_season})
    cutoff = date(2020, 10, 1)
    altered = [replace(full_season[0], home_goals=4)] + full_season[1:]
    adjustment = {
        "team_id": teams[0],
        "points": -6,
        "known_on": "2020-09-01",
        "source": "test sanction",
    }
    result = simulate_season(FixedModel(cutoff), altered, [], teams, cutoff, 1, 0, [adjustment])
    row = result["teams"][0]
    assert row["mean_points"] == 51
    assert row["mean_goal_difference"] == 3
    assert result["remaining_matches"] == 0
    with pytest.raises(ValueError, match="not known"):
        simulate_season(
            FixedModel(cutoff),
            altered,
            [],
            teams,
            cutoff,
            1,
            0,
            [{**adjustment, "known_on": "2020-10-02"}],
        )


def test_head_to_head_breaks_decisive_tie_but_not_shared_midtable():
    teams = ["a", "b", "c", "d"]
    points = np.array([60, 60, 30, 20])
    zeros = np.zeros(4, dtype=int)
    head = np.zeros((4, 4), dtype=int)
    away = np.zeros_like(head)
    head[1, 0] = 4
    head[0, 1] = 1
    order, ties, unresolved, used = rank_table(
        teams, points, zeros, zeros, head, away, np.random.default_rng(0), relegated=0
    )
    assert order[:2] == [1, 0]
    assert not ties and not unresolved and used
    head[:] = 3
    away[1, 0] = 2
    order, _, _, _ = rank_table(
        teams, points, zeros, zeros, head, away, np.random.default_rng(0), relegated=0
    )
    assert order[0] == 1
    points[:] = [60, 30, 30, 20]
    _, ties, unresolved, used = rank_table(
        teams, points, zeros, zeros, head, away, np.random.default_rng(0), relegated=0
    )
    assert ties == [(1, 3)] and not used and not unresolved


def test_europe_cup_passdowns_and_external_winner():
    teams = [f"t{i}" for i in range(20)]
    scenario = EuropeScenario("four places, both cup winners in UCL", 4, "t0", "t1")
    places = european_places(teams, scenario)
    assert places["champions_league"] == set(teams[:4])
    assert places["europa_league"] == {"t4", "t5"}
    assert places["conference_league"] == {"t6"}
    scenario = EuropeScenario("five places, cup winners outside", 5, "non-pl-team", "t10")
    places = european_places(teams, scenario)
    assert places["europa_league"] == {"t5", "non-pl-team"}
    assert places["conference_league"] == {"t10"}
    scenario = EuropeScenario("cup winner takes league Europa place", 4, "t4", "t4")
    places = european_places(teams, scenario)
    assert places["europa_league"] == {"t4", "t5"}
    assert places["conference_league"] == {"t6"}


def test_historical_appeal_is_not_backdated():
    def everton_points(cutoff):
        return sum(
            event["points"]
            for event in reviewed_adjustments("eng-premier-league", "2023-2024", cutoff)
            if event["team_id"] == "everton"
        )

    assert everton_points(date(2023, 11, 17)) == 0
    assert everton_points(date(2023, 11, 18)) == -10
    assert everton_points(date(2024, 2, 26)) == -10
    assert everton_points(date(2024, 2, 27)) == -6
    assert everton_points(date(2024, 4, 9)) == -8


def test_future_score_mutation_cannot_change_a_simulated_remainder(full_season):
    cutoff = date(2020, 8, 10)
    config = {
        "competition_id": "eng-premier-league",
        "train_window_days": 365,
        "min_train_matches": 1,
        "models": [{"id": "poisson", "kind": "attack_defense_poisson"}],
    }

    def simulate(matches):
        model, _, _ = fitted_model(matches, config, "poisson", cutoff)
        teams = sorted({m.fixture.home_team_id for m in matches})
        played = [m for m in matches if m.available_on <= cutoff]
        remaining = [m.fixture for m in matches if m.available_on > cutoff]
        return simulate_season(model, played, remaining, teams, cutoff, 12, 42)

    mutated = [
        replace(m, home_goals=15, away_goals=12) if m.available_on > cutoff else m
        for m in full_season
    ]
    assert simulate(full_season) == simulate(mutated)


def test_conditional_european_slots_are_conserved(full_season):
    cutoff = date(2020, 8, 1)
    teams = sorted({m.fixture.home_team_id for m in full_season})
    europe = EuropeScenario("hypothetical cup winners", 5, teams[0], teams[1])
    result = simulate_season(
        FixedModel(cutoff),
        [],
        [m.fixture for m in full_season],
        teams,
        cutoff,
        10,
        10,
        europe=europe,
    )
    for competition, slots in (
        ("champions_league", 5),
        ("europa_league", 2),
        ("conference_league", 1),
    ):
        assert sum(
            row["conditional_europe_probabilities"][competition] for row in result["teams"]
        ) == pytest.approx(slots)


def test_simulation_reuses_one_joint_state_per_path(full_season):
    teams = sorted({m.fixture.home_team_id for m in full_season})
    cutoff = date(2020, 8, 1)

    class UncertainModel:
        as_of = cutoff
        calls = 0

        def predict_match(self, fixture):
            raise AssertionError("Posterior simulation must condition on its shared states")

        def sample_forecast_state(self, rng, size=1):
            self.calls += 1
            strong = rng.random(size) < 0.5

            class States:
                as_of = cutoff

                def sample_scores(self, fixture, rng, log_rate_shift=0.0):
                    home, away = np.zeros(size, dtype=int), np.zeros(size, dtype=int)
                    if fixture.home_team_id == teams[0]:
                        home, away = strong.astype(int), (~strong).astype(int)
                    if fixture.away_team_id == teams[0]:
                        home, away = (~strong).astype(int), strong.astype(int)
                    return home, away

            states = States()
            states.size = size
            return states

    model = UncertainModel()
    result = simulate_season(model, [], [m.fixture for m in full_season], teams, cutoff, 64, 13)
    assert model.calls == 1
    assert result["state_uncertainty"] == "posterior"
    assert set(result["teams"][0]["points_distribution"]) == {"0", "114"}
    assert sum(t["title_probability"] for t in result["teams"]) == pytest.approx(1)
    assert all(t["position_sd"] >= 0 for t in result["teams"])
    assert all(len(t["position_quantiles_05_50_95"]) == 3 for t in result["teams"])
    assert all(set(t["position_intervals"]) == {"50", "80", "90"} for t in result["teams"])
    assert all(set(t["points_intervals"]) == {"50", "80", "90"} for t in result["teams"])
    assert sum(t["relegation_probability"] for t in result["teams"]) == pytest.approx(3)


def test_championship_projection_conserves_promotion_and_playoff_slots():
    from epl_forecast.schema import Fixture, Match, fixture_id

    teams = [f"club-{i}" for i in range(24)]
    day = date(2026, 8, 10)
    games = [
        Match(
            Fixture(
                fixture_id("eng-championship", "2026-2027", h, a),
                "eng-championship",
                "2026-2027",
                day,
                h,
                a,
            ),
            1,
            1,
        )
        for h in teams
        for a in teams
        if h != a
    ]
    cutoff = date(2026, 8, 11)
    result = simulate_season(FixedModel(cutoff), games, [], teams, cutoff, 10, 7)
    assert len(result["teams"]) == 24
    assert sum(r["automatic_promotion_probability"] for r in result["teams"]) == pytest.approx(2)
    assert sum(r["playoff_qualification_probability"] for r in result["teams"]) == pytest.approx(6)
    assert sum(r["playoff_promotion_probability"] for r in result["teams"]) == pytest.approx(1)
    assert sum(r["promotion_probability"] for r in result["teams"]) == pytest.approx(3)
    assert sum(r["relegation_probability"] for r in result["teams"]) == pytest.approx(3)
    assert all("top_four_probability" not in r for r in result["teams"])
    assert result["ranking_rules"] == "efl"
    assert result["disciplinary_tiebreaks_available"] is False
    assert result["playoff_model"]["format"] == "2026-six-team-seven-match"
    assert "equal advancement" in result["playoff_model"]["tied_knockout_scores"]


def test_six_team_playoff_bracket_respects_seed_paths():
    teams = [f"club-{i}" for i in range(24)]
    orders = np.tile(np.arange(24), (200, 1))
    winners, details = simulate_playoffs(
        FixedModel(date(2026, 8, 1)),
        orders,
        teams,
        "eng-championship",
        "2026-2027",
        date(2027, 5, 1),
        np.random.default_rng(11),
    )
    assert set(winners) <= set(teams[2:6])
    assert not set(winners) & set(teams[6:8])
    assert details["format"] == "2026-six-team-seven-match"


class PathStates:
    """One dominant club per path, so a bracket result reveals which draw it used."""

    evolves_future_states = False

    def __init__(self, teams, as_of, size):
        self.as_of, self.size = as_of, size
        self.champion = [teams[index % len(teams)] for index in range(size)]

    def sample_scores(self, fixture, rng, paths=None, log_rate_shift=0.0):
        chosen = range(self.size) if paths is None else list(paths)
        home = [5 if self.champion[p] == fixture.home_team_id else 0 for p in chosen]
        away = [5 if self.champion[p] == fixture.away_team_id else 0 for p in chosen]
        return np.array(home), np.array(away)


class PathStateModel(FixedModel):
    def __init__(self, as_of, teams):
        super().__init__(as_of)
        self.teams = teams

    def sample_forecast_state(self, rng, size=1):
        return PathStates(self.teams, self.as_of, size)


def championship_fixtures(teams, day, season="2026-2027"):
    from epl_forecast.schema import Fixture, fixture_id

    return [
        Fixture(fixture_id("eng-championship", season, h, a), "eng-championship", season, day, h, a)
        for h in teams
        for a in teams
        if h != a
    ]


def test_playoff_bracket_uses_each_path_own_latent_state():
    teams = [f"club-{i}" for i in range(24)]
    orders = np.tile(np.arange(24), (48, 1))
    states = PathStates(teams, date(2026, 8, 1), 48)
    winners, details = simulate_playoffs(
        FixedModel(date(2026, 8, 1)),
        orders,
        teams,
        "eng-championship",
        "2026-2027",
        date(2027, 5, 1),
        np.random.default_rng(3),
        states,
    )
    bracket = set(teams[2:8])
    for path, champion in enumerate(states.champion):
        if champion in bracket:
            assert winners[path] == champion
    assert "path-specific" in details["state_conditioning"]


def test_playoff_conditioning_leaves_the_regular_season_untouched():
    teams = [f"club-{i}" for i in range(24)]
    cutoff = date(2026, 8, 1)
    remaining = championship_fixtures(teams, date(2026, 8, 10))
    model = PathStateModel(cutoff, teams)
    simulated = simulate_season(model, [], remaining, teams, cutoff, 24, 5)
    observed = simulate_season(model, [], remaining, teams, cutoff, 24, 5, playoff_winner=teams[0])
    for left, right in zip(simulated["teams"], observed["teams"], strict=True):
        assert left["points_distribution"] == right["points_distribution"]
        assert left["position_probabilities"] == right["position_probabilities"]
    assert simulated["playoff_model"]["state_conditioning"].startswith("path-specific")
    assert sum(r["playoff_promotion_probability"] for r in simulated["teams"]) == pytest.approx(1)


def test_delayed_season_playoff_dates_stay_inside_schema():
    teams = [f"club-{i}" for i in range(24)]
    orders = np.tile(np.arange(24), (20, 1))
    winners, details = simulate_playoffs(
        FixedModel(date(2020, 7, 1)),
        orders,
        teams,
        "eng-championship",
        "2019-2020",
        date(2020, 7, 22),
        np.random.default_rng(12),
    )
    assert len(winners) == 20
    assert details["synthetic_match_dates"][-1] == "2020-07-31"
    assert details["date_offset_scale"] == pytest.approx(9 / 29)


@pytest.mark.parametrize(
    "season,boundary", [("2025-2026", 2), ("2025-2026", 6), ("2026-2027", 8), ("2026-2027", 21)]
)
def test_efl_decisive_boundaries_and_head_to_head(season, boundary):
    teams = [f"t{i}" for i in range(24)]
    points = np.arange(24, 0, -1) * 3
    a, b = boundary - 1, boundary
    points[b] = points[a]
    zeros = np.zeros(24, dtype=int)
    head = np.zeros((24, 24), dtype=int)
    goals = np.zeros_like(head)
    kwargs = dict(
        rules=league_rules("eng-championship", season),
        head_goals=goals,
        wins=zeros,
        away_goals=zeros,
    )
    _, ties, unresolved, used = rank_table(
        teams, points, zeros, zeros, head, goals, np.random.default_rng(0), **kwargs
    )
    assert ties == [(a, b + 1)] and unresolved and used
    head[b, a], head[a, b] = 4, 1
    order, ties, unresolved, used = rank_table(
        teams, points, zeros, zeros, head, goals, np.random.default_rng(0), **kwargs
    )
    assert order[a : b + 1] == [b, a]
    assert not ties and not unresolved and used


@pytest.mark.parametrize(
    "criterion",
    [
        "head_points",
        "head_difference",
        "head_goals",
        "wins",
        "away_goals",
        "discipline",
        "sendings_off",
    ],
)
def test_efl_criteria_precedence_in_three_team_midtable_tie(criterion):
    teams = ["leader", "a", "b", "c", "last"]
    points = np.array([90, 50, 50, 50, 10])
    zeros = np.zeros(5, dtype=int)
    head = np.zeros((5, 5), dtype=int)
    goals = np.zeros_like(head)
    wins, away, discipline, reds = (zeros.copy() for _ in range(4))
    if criterion == "head_points":
        head[2, 1] = 3
        goals[1, 2] = 5
    elif criterion == "head_difference":
        goals[2, 1] = 2
    elif criterion == "head_goals":
        goals[2, 3] = goals[3, 2] = 2
        goals[1, 2] = goals[2, 1] = 1
    elif criterion == "wins":
        wins[2] = 20
        away[1] = 50
    elif criterion == "away_goals":
        away[2] = 20
        discipline[2] = 100
    elif criterion == "discipline":
        discipline[:] = 20
        discipline[2] = 10
        reds[2] = 5
    else:
        reds[:] = 2
        reds[2] = 1
    order, _, _, used = rank_table(
        teams,
        points,
        zeros,
        zeros,
        head,
        np.zeros_like(head),
        np.random.default_rng(0),
        rules=league_rules("eng-championship", "2026-2027"),
        head_goals=goals,
        wins=wins,
        away_goals=away,
        disciplinary_points=discipline,
        serious_sendings_off=reds,
    )
    assert order[1] == 2 and used


def test_efl_does_not_use_head_to_head_away_goals():
    teams = ["a", "b"]
    zeros = np.zeros(2, dtype=int)
    head = np.array([[0, 3], [3, 0]])
    goals = np.array([[0, 2], [2, 0]])
    away = np.array([[0, 1], [2, 0]])
    _, ties, unresolved, _ = rank_table(
        teams,
        zeros,
        zeros,
        zeros,
        head,
        away,
        np.random.default_rng(0),
        rules=league_rules("eng-championship", "2026-2027"),
        head_goals=goals,
        wins=zeros,
        away_goals=zeros,
    )
    assert ties == [(0, 2)] and unresolved


LOWER_DIVISIONS = [("eng-league-one", 2, 6, 4), ("eng-league-two", 3, 7, 2)]


@pytest.mark.parametrize("competition,automatic,playoff_end,relegated", LOWER_DIVISIONS)
def test_reviewed_lower_division_editions_match_their_rules(
    competition, automatic, playoff_end, relegated
):
    evidence = reviewed_rules_evidence(competition, "2026-2027")
    rules = league_rules(competition, "2026-2027")
    championship = reviewed_rules_evidence("eng-championship", "2026-2027")
    assert evidence["source_sha256"] == championship["source_sha256"]
    assert (evidence["automatic_promotion"], evidence["playoff_end"], evidence["relegated"]) == (
        automatic,
        playoff_end,
        relegated,
    )
    assert (rules.automatic_promotion, rules.playoff_end, rules.relegated) == (
        automatic,
        playoff_end,
        relegated,
    )
    assert rules.ranking == "efl" and rules.playoff_places == 4


def division_fixtures(competition, teams, day, season="2026-2027"):
    from epl_forecast.schema import Fixture, fixture_id

    return [
        Fixture(fixture_id(competition, season, h, a), competition, season, day, h, a)
        for h in teams
        for a in teams
        if h != a
    ]


@pytest.mark.parametrize("competition,automatic,playoff_end,relegated", LOWER_DIVISIONS)
def test_lower_division_projection_awards_its_own_places(
    competition, automatic, playoff_end, relegated
):
    from epl_forecast.schema import Match

    teams = [f"club-{i}" for i in range(24)]
    games = [Match(f, 1, 1) for f in division_fixtures(competition, teams, date(2026, 8, 10))]
    cutoff = date(2026, 8, 11)
    result = simulate_season(FixedModel(cutoff), games, [], teams, cutoff, 10, 7)
    rows = result["teams"]
    assert sum(r["automatic_promotion_probability"] for r in rows) == pytest.approx(automatic)
    assert sum(r["playoff_qualification_probability"] for r in rows) == pytest.approx(4)
    assert sum(r["playoff_promotion_probability"] for r in rows) == pytest.approx(1)
    assert sum(r["promotion_probability"] for r in rows) == pytest.approx(automatic + 1)
    assert sum(r["relegation_probability"] for r in rows) == pytest.approx(relegated)
    assert result["playoff_model"]["format"] == "four-team-five-match"
    assert result["disciplinary_tiebreaks_available"] is False


def test_four_team_bracket_starts_below_automatic_promotion():
    teams = [f"club-{i}" for i in range(24)]
    orders = np.tile(np.arange(24), (200, 1))
    winners, details = simulate_playoffs(
        FixedModel(date(2026, 8, 1)),
        orders,
        teams,
        "eng-league-two",
        "2026-2027",
        date(2027, 5, 1),
        np.random.default_rng(5),
    )
    assert set(winners) == set(teams[3:7])
    assert details["format"] == "four-team-five-match"


def test_lower_division_bracket_uses_each_path_own_latent_state():
    teams = [f"club-{i}" for i in range(24)]
    states = PathStates(teams, date(2026, 8, 1), 48)
    winners, _ = simulate_playoffs(
        FixedModel(date(2026, 8, 1)),
        np.tile(np.arange(24), (48, 1)),
        teams,
        "eng-league-one",
        "2026-2027",
        date(2027, 5, 1),
        np.random.default_rng(3),
        states,
    )
    for path, champion in enumerate(states.champion):
        if champion in teams[2:6]:
            assert winners[path] == champion


def test_playoff_winner_ignores_clubs_relegated_into_the_division_above():
    from epl_forecast.schema import Fixture, Match, fixture_id
    from epl_forecast.season_evaluation import playoff_winner

    def games(competition, season, pairs):
        day = date(int(season[:4]), 9, 1)
        return [
            Match(
                Fixture(fixture_id(competition, season, h, a), competition, season, day, h, a), 1, 0
            )
            for h, a in pairs
        ]

    matches = (
        games("eng-league-one", "2024-2025", [("a", "b"), ("c", "d"), ("e", "a")])
        + games("eng-championship", "2024-2025", [("x", "y"), ("y", "z")])
        + games("eng-championship", "2025-2026", [("x", "a"), ("b", "c"), ("p", "x")])
    )
    order = ["a", "b", "c", "d", "e"]
    assert playoff_winner(matches, "eng-league-one", "2024-2025", order) == "c"
