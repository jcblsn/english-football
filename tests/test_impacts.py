from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest
from test_publication import sample_forecast

from epl_forecast.live import LiveSeason
from epl_forecast.live_forecast import started_slate, weekly_window
from epl_forecast.models.base import Forecast
from epl_forecast.publication import (
    IMPACT_MOVEMENT_FLOOR,
    UNAVAILABLE_IMPACT,
    check_publishable,
    derive_forecast,
    derive_impact,
    load_policy,
    update_impact_state,
)
from epl_forecast.schema import Fixture, fixture_id
from epl_forecast.simulation import (
    EVERY_TEAM,
    MINIMUM_CONDITIONAL_SAMPLES,
    OUTCOME_NAMES,
    conditional_impacts,
    simulate_season,
)

CUTOFF = date(2020, 8, 10)
MATCH = "eng-premier-league:2026-2027:arsenal:chelsea"
KICKOFF = "2026-09-12T14:00:00+00:00"


class RandomScores:
    def __init__(self, home_rate, away_rate):
        self.home_rate, self.away_rate = home_rate, away_rate

    def sample(self, rng, size):
        return rng.poisson(self.home_rate, size), rng.poisson(self.away_rate, size)


class RandomModel:
    def __init__(self, as_of, teams):
        self.as_of = as_of
        self.rates = {team: 0.8 + 0.04 * index for index, team in enumerate(sorted(teams))}

    def predict_match(self, fixture):
        return Forecast(
            (0.4, 0.3, 0.3),
            RandomScores(self.rates[fixture.home_team_id], self.rates[fixture.away_team_id]),
        )


class AlwaysHomeWin:
    def sample(self, rng, size):
        return np.ones(size, dtype=int), np.zeros(size, dtype=int)


class FixedModel:
    def __init__(self, as_of):
        self.as_of = as_of

    def predict_match(self, fixture):
        return Forecast((1.0, 0.0, 0.0), AlwaysHomeWin())


def season_parts(full_season):
    teams = sorted({m.fixture.home_team_id for m in full_season})
    played = [m for m in full_season if m.available_on <= CUTOFF]
    remaining = [m.fixture for m in full_season if m.available_on > CUTOFF]
    return teams, played, remaining


def run(full_season, model=None, simulations=400, count=3):
    teams, played, remaining = season_parts(full_season)
    wanted = {fixture.match_id for fixture in remaining[:count]}
    return simulate_season(
        model or RandomModel(CUTOFF, teams),
        played,
        remaining,
        teams,
        CUTOFF,
        simulations,
        7,
        impact_fixtures=wanted,
    )


def participant_impacts(outcomes, event_paths, team_index, simulations):
    """The participants-only calculation this feature replaced, kept as a reference."""
    fixtures = {}
    for match_id, (fixture, codes) in sorted(outcomes.items()):
        masks = [codes == index for index in range(3)]
        counts = [int(mask.sum()) for mask in masks]
        rows = {}
        for team in (fixture.home_team_id, fixture.away_team_id):
            column = team_index[team]
            for event, values in event_paths.items():
                indicators = values[:, column].astype(float)
                baseline = float(indicators.mean())
                conditional, error = {}, {}
                movement = 0.0
                for name, mask, count in zip(OUTCOME_NAMES, masks, counts, strict=True):
                    if not count:
                        conditional[name], error[name] = None, None
                        continue
                    subset = indicators[mask]
                    conditional[name] = float(subset.mean())
                    error[name] = float(np.sqrt(subset.var() / count))
                    movement += count / simulations * (conditional[name] - baseline) ** 2
                present = [value for value in conditional.values() if value is not None]
                rows[team, event] = {
                    "baseline": baseline,
                    "conditional": conditional,
                    "standard_error": error,
                    "rms_movement": float(np.sqrt(movement)),
                    "swing": float(max(present) - min(present)),
                    "sufficient_sample": min(counts) >= MINIMUM_CONDITIONAL_SAMPLES,
                }
        fixtures[match_id] = rows
    return fixtures


def test_conditioning_returns_the_published_event_in_aggregate(full_season):
    result = run(full_season)
    impacts = result["match_impacts"]
    events = {
        (row["team_id"], event): value
        for row in result["teams"]
        for event, value in row.items()
        if event.endswith("_probability")
    }
    assert len(impacts["fixtures"]) == 3
    assert impacts["horizon_days"] == 7
    for fixture in impacts["fixtures"]:
        counts = fixture["outcome_counts"]
        assert sum(counts.values()) == result["simulations"]
        for row in fixture["impacts"]:
            assert row["baseline"] == pytest.approx(events[(row["team_id"], row["event"])])
            recovered = sum(
                counts[name] / result["simulations"] * row["conditional"][name]
                for name in OUTCOME_NAMES
                if counts[name]
            )
            assert recovered == pytest.approx(row["baseline"], abs=1e-12)


def test_every_club_is_measured_against_every_fixture(full_season):
    result = run(full_season)
    impacts = result["match_impacts"]
    clubs = {row["team_id"] for row in result["teams"]}
    assert impacts["coverage"] == EVERY_TEAM
    for fixture in impacts["fixtures"]:
        events = {row["event"] for row in fixture["impacts"]}
        assert {row["team_id"] for row in fixture["impacts"]} == clubs
        assert len(fixture["impacts"]) == len(clubs) * len(events)
        outsiders = [
            row
            for row in fixture["impacts"]
            if row["team_id"] not in (fixture["home_team_id"], fixture["away_team_id"])
        ]
        assert any(row["rms_movement"] > 0 for row in outsiders)


def test_the_all_club_calculation_reproduces_the_participant_rows():
    rng = np.random.default_rng(11)
    simulations = 500
    teams = [f"team-{index:02d}" for index in range(6)]
    team_index = {team: index for index, team in enumerate(teams)}
    fixture = Fixture(
        fixture_id("eng-premier-league", "2020-2021", teams[1], teams[4]),
        "eng-premier-league",
        "2020-2021",
        date(2020, 8, 15),
        teams[1],
        teams[4],
    )
    # Shared ranks split their mass, so an event indicator is not always zero or one.
    event_paths = {
        "title_probability": rng.choice([0.0, 0.5, 1.0], (simulations, len(teams))),
        "relegation_probability": rng.choice([0.0, 1.0], (simulations, len(teams))),
    }
    outcomes = {fixture.match_id: (fixture, rng.integers(0, 3, simulations).astype(np.int8))}
    reference = participant_impacts(outcomes, event_paths, team_index, simulations)
    result = conditional_impacts(outcomes, event_paths, teams, simulations, 7)
    rows = {(row["team_id"], row["event"]): row for row in result["fixtures"][0]["impacts"]}
    assert len(rows) == len(teams) * len(event_paths)
    for key, expected in reference[fixture.match_id].items():
        row = rows[key]
        assert row["baseline"] == pytest.approx(expected["baseline"], abs=1e-12)
        assert row["rms_movement"] == pytest.approx(expected["rms_movement"], abs=1e-12)
        assert row["swing"] == pytest.approx(expected["swing"], abs=1e-12)
        assert row["sufficient_sample"] == expected["sufficient_sample"]
        for name in OUTCOME_NAMES:
            assert row["conditional"][name] == pytest.approx(
                expected["conditional"][name], abs=1e-12
            )
            assert row["standard_error"][name] == pytest.approx(
                expected["standard_error"][name], abs=1e-12
            )


def test_a_certain_result_moves_nothing_and_is_a_thin_sample(full_season):
    impacts = run(full_season, model=FixedModel(CUTOFF), simulations=8, count=1)["match_impacts"]
    fixture = impacts["fixtures"][0]
    assert fixture["outcome_counts"] == {"home": 8, "draw": 0, "away": 0}
    assert impacts["smallest_outcome_count"] == 0
    for row in fixture["impacts"]:
        assert row["rms_movement"] == pytest.approx(0.0)
        assert row["swing"] == pytest.approx(0.0)
        assert row["conditional"]["draw"] is None and row["conditional"]["away"] is None
        assert row["conditional"]["home"] == pytest.approx(row["baseline"])
        assert not row["sufficient_sample"]


def test_impacts_rank_by_movement_and_report_their_swing(full_season):
    impacts = run(full_season)["match_impacts"]
    tops = [fixture["top_rms_movement"] for fixture in impacts["fixtures"]]
    assert tops == sorted(tops, reverse=True)
    for fixture in impacts["fixtures"]:
        movements = [row["rms_movement"] for row in fixture["impacts"]]
        assert movements == sorted(movements, reverse=True)
        assert fixture["top_rms_movement"] == movements[0]
        for row in fixture["impacts"]:
            present = [value for value in row["conditional"].values() if value is not None]
            assert row["swing"] == pytest.approx(max(present) - min(present))
            assert row["swing"] >= row["rms_movement"] - 1e-12


def test_no_requested_fixtures_publishes_no_impact_surface(full_season):
    teams, played, remaining = season_parts(full_season)
    result = simulate_season(RandomModel(CUTOFF, teams), played, remaining, teams, CUTOFF, 8, 7)
    assert result["match_impacts"] is None
    assert derive_impact(result, {}) is None


def test_derive_impact_publishes_every_club_of_the_whole_slate(full_season):
    result = run(full_season, count=8)
    kickoffs = {
        fixture["match_id"]: "2020-08-11T14:00:00+00:00"
        for fixture in result["match_impacts"]["fixtures"]
    }
    published = derive_impact(result, kickoffs)
    assert len(published["fixtures"]) == 8
    assert published["horizon_days"] == 7
    assert published["coverage"] == EVERY_TEAM
    assert published["movement_floor"] == IMPACT_MOVEMENT_FLOOR
    for fixture in published["fixtures"]:
        assert fixture["kickoff_time"] == "2020-08-11T14:00:00+00:00"
        assert fixture["status"] == "scheduled" and fixture["outcome"] is None
        assert fixture["carried_from"] is None
        assert fixture["max_standard_error"] > 0
        for block in fixture["impacts"].values():
            lengths = {len(values) for values in block.values()}
            assert len(lengths) == 1
            assert block["rms_movement"] == sorted(block["rms_movement"], reverse=True)
            assert min(block["rms_movement"]) >= IMPACT_MOVEMENT_FLOOR - 5e-7
            assert len(set(block["team_id"])) == len(block["team_id"])


def test_a_club_ranks_the_slate_by_its_own_movement(full_season):
    result = run(full_season, count=6)
    published = derive_impact(result, {})
    event = "relegation_probability"
    club = published["fixtures"][0]["impacts"][event]["team_id"][0]
    ranked = []
    for fixture in published["fixtures"]:
        block = fixture["impacts"].get(event, {})
        if club in block.get("team_id", []):
            index = block["team_id"].index(club)
            ranked.append((block["rms_movement"][index], fixture))
    ranked.sort(key=lambda row: row[0], reverse=True)
    assert len(ranked) > 1
    assert any(
        club not in (fixture["home_team_id"], fixture["away_team_id"]) for _, fixture in ranked
    )
    best = max(ranked, key=lambda row: row[0])
    assert ranked[0][1]["match_id"] == best[1]["match_id"]


def test_the_slate_starts_on_the_london_day_and_ends_at_the_horizon():
    observed = datetime(2026, 9, 12, 15, 30, tzinfo=UTC)
    start, end = weekly_window(observed, 7)
    assert start == datetime(2026, 9, 11, 23, 0, tzinfo=UTC)
    assert end == observed + timedelta(days=7)


def test_the_slate_follows_the_london_clock_changes():
    # Clocks go back on 2026-10-25, so that London day opens an hour before midnight UTC.
    assert weekly_window(datetime(2026, 10, 25, 12, tzinfo=UTC), 7)[0] == datetime(
        2026, 10, 24, 23, tzinfo=UTC
    )
    # Clocks go forward on 2026-03-29, so that London day opens at midnight UTC.
    assert weekly_window(datetime(2026, 3, 29, 12, tzinfo=UTC), 7)[0] == datetime(
        2026, 3, 29, 0, tzinfo=UTC
    )
    # Late in the UTC evening, London is already on the next day.
    assert weekly_window(datetime(2026, 5, 30, 23, 30, tzinfo=UTC), 7)[0] == datetime(
        2026, 5, 30, 23, tzinfo=UTC
    )


def detail(match_id, status, kickoff, home_goals=None, away_goals=None):
    return {
        "match_id": match_id,
        "home_team_id": "arsenal",
        "away_team_id": "chelsea",
        "status": status,
        "kickoff_time": kickoff,
        "match_date": kickoff[:10],
        "home_goals": home_goals,
        "away_goals": away_goals,
        "started": status == "finished",
    }


def test_a_matchday_afternoon_keeps_the_matches_that_started():
    observed = datetime(2026, 9, 12, 15, 30, tzinfo=UTC)
    details = {
        "yesterday": detail("yesterday", "finished", "2026-09-11T19:00:00+00:00", 1, 0),
        "lunchtime": detail("lunchtime", "finished", "2026-09-12T11:30:00+00:00", 2, 2),
        "in-play": detail("in-play", "in_progress", "2026-09-12T14:00:00+00:00"),
        "afternoon": detail("afternoon", "scheduled", "2026-09-12T16:30:00+00:00"),
        "next-week": detail("next-week", "scheduled", "2026-09-19T14:00:00+00:00"),
    }
    live = LiveSeason("2026-2027", observed, {}, [], [], details, {})
    start, _ = weekly_window(observed, 7)
    slate = started_slate(live, start)
    assert [row["match_id"] for row in slate] == ["lunchtime", "in-play"]
    assert (slate[0]["status"], slate[0]["outcome"]) == ("finished", "D")
    assert (slate[1]["status"], slate[1]["outcome"]) == ("in_progress", None)


def impact_block(coverage=EVERY_TEAM, movement=0.05):
    rows = []
    for team, baseline in (("arsenal", 0.5), ("chelsea", 0.5)):
        for event in ("title_probability", "relegation_probability"):
            rows.append(
                {
                    "team_id": team,
                    "event": event,
                    "baseline": baseline,
                    "conditional": {"home": 0.6, "draw": 0.45, "away": 0.35},
                    "standard_error": {"home": 0.004, "draw": 0.005, "away": 0.005},
                    "rms_movement": movement,
                    "swing": 0.25,
                    "sufficient_sample": True,
                }
            )
    return {
        "horizon_days": 7,
        "simulations": 10000,
        "minimum_conditional_samples": MINIMUM_CONDITIONAL_SAMPLES,
        "smallest_outcome_count": 2500,
        "coverage": coverage,
        "window_start": "2026-09-11T23:00:00+00:00",
        "window_end": "2026-09-18T12:00:00+00:00",
        "fixtures": [
            {
                "match_id": MATCH,
                "match_date": "2026-09-12",
                "home_team_id": "arsenal",
                "away_team_id": "chelsea",
                "outcome_counts": {"home": 5000, "draw": 2500, "away": 2500},
                "impacts": rows,
                "top_rms_movement": movement,
            }
        ],
        "basis": "Conditional forecasts aggregated from one season simulation.",
    }


def scheduled_forecast(generated, coverage=EVERY_TEAM, movement=0.05):
    forecast = sample_forecast(generated=generated)
    forecast["simulation"]["match_impacts"] = impact_block(coverage, movement)
    forecast["impact_window"] = {
        "horizon_days": 7,
        "window_start": "2026-09-11T23:00:00+00:00",
        "window_end": "2026-09-18T12:00:00+00:00",
        "started": [],
    }
    return forecast


def played_forecast(generated, status="finished", outcome="H"):
    """The same season once the fixture has kicked off."""
    forecast = scheduled_forecast(generated)
    forecast["matches"][0]["status"] = status
    forecast["simulation"]["match_impacts"]["fixtures"] = []
    forecast["impact_window"]["started"] = [
        {
            "match_id": MATCH,
            "home_team_id": "arsenal",
            "away_team_id": "chelsea",
            "kickoff_time": KICKOFF,
            "match_date": "2026-09-12",
            "status": status,
            "outcome": outcome,
        }
    ]
    return forecast


def publish(state, generated, forecast_id, **kwargs):
    document = derive_forecast(scheduled_forecast(generated, **kwargs), forecast_id)
    return update_impact_state(document, state)


def carried(
    state,
    generated="2026-09-12T18:00:00+00:00",
    forecast_id="2026-09-12T180000Z",
    **kwargs,
):
    document = derive_forecast(played_forecast(generated, **kwargs), forecast_id)
    return update_impact_state(document, state)


def test_a_match_in_play_shows_its_last_pre_kickoff_impact():
    state = {}
    publish(state, "2026-09-12T09:00:00+00:00", "2026-09-12T090000Z", movement=0.07)
    document = carried(state, status="in_progress", outcome=None)
    check_publishable(document, load_policy())
    fixture = document["impact"]["fixtures"][0]
    assert fixture["status"] == "in_progress" and fixture["outcome"] is None
    assert fixture["carried_from"]["forecast_id"] == "2026-09-12T090000Z"
    assert fixture["impacts"]["title_probability"]["rms_movement"] == [0.07, 0.07]


def test_a_finished_fixture_shows_its_last_pre_kickoff_impact():
    state = {}
    publish(state, "2026-09-11T12:00:00+00:00", "2026-09-11T120000Z", movement=0.02)
    publish(state, "2026-09-12T09:00:00+00:00", "2026-09-12T090000Z", movement=0.07)
    document = carried(state)
    check_publishable(document, load_policy())
    fixture = document["impact"]["fixtures"][0]
    assert fixture["status"] == "finished" and fixture["outcome"] == "H"
    assert fixture["carried_from"]["forecast_id"] == "2026-09-12T090000Z"
    assert "unavailable_reason" not in fixture
    block = fixture["impacts"]["title_probability"]
    assert block["rms_movement"] == [0.07, 0.07]
    assert block["baseline"] == [0.5, 0.5]
    assert block["home"] == [0.6, 0.6]


def test_a_forecast_made_after_the_kickoff_cannot_supply_the_impact():
    state = {}
    publish(state, "2026-09-12T16:00:00+00:00", "2026-09-12T160000Z")
    document = carried(state)
    fixture = document["impact"]["fixtures"][0]
    assert fixture["carried_from"] is None
    assert fixture["impacts"] == {}
    assert fixture["unavailable_reason"] == UNAVAILABLE_IMPACT
    check_publishable(document, load_policy())


def test_impacts_from_before_this_feature_are_not_carried_forward():
    state = {}
    publish(state, "2026-09-12T09:00:00+00:00", "2026-09-12T090000Z", coverage="participants")
    fixture = carried(state)["impact"]["fixtures"][0]
    assert fixture["carried_from"] is None
    assert fixture["unavailable_reason"] == UNAVAILABLE_IMPACT


def test_a_record_that_holds_no_numbers_is_not_carried_forward():
    state = {}
    carried(state, "2026-09-12T13:00:00+00:00", "2026-09-12T130000Z")
    fixture = carried(state)["impact"]["fixtures"][0]
    assert fixture["carried_from"] is None
    assert fixture["unavailable_reason"] == UNAVAILABLE_IMPACT


def test_an_in_play_record_remains_available_for_the_finished_forecast():
    state = {}
    publish(state, "2026-09-12T09:00:00+00:00", "2026-09-12T090000Z", movement=0.07)
    carried(state, status="in_progress", outcome=None)
    second = carried(state, "2026-09-12T21:00:00+00:00", "2026-09-12T210000Z")
    assert second["impact"]["fixtures"][0]["carried_from"]["forecast_id"] == "2026-09-12T090000Z"
