from datetime import date, timedelta

import numpy as np
import pytest

from epl_forecast.models.poisson import PoissonMixture
from epl_forecast.research.personnel_mean import (
    quality_shift,
    realized_continuity,
    shifted_scores,
)
from epl_forecast.schema import Fixture, Match, fixture_id


def test_quality_shift_has_the_intended_symmetry():
    shift = quality_shift(0.4, 0.1, 0.5)
    assert shift == pytest.approx([-0.15, 0.15])
    assert quality_shift(0.1, 0.4, 0.5) == pytest.approx(-shift)
    assert quality_shift(0.4, 0.4, 0.5) == pytest.approx([0.0, 0.0])


def test_zero_shift_recovers_scores_without_mutation():
    scores = PoissonMixture(np.log([1.4, 1.0]), np.array([[0.1, 0.02], [0.02, 0.1]]))
    before = scores.home_rates.copy(), scores.away_rates.copy()
    shifted = shifted_scores(scores, quality_shift(0.3, 0.3, 1.0))
    assert shifted.outcome_probabilities() == pytest.approx(scores.outcome_probabilities())
    assert shifted.log_probability(2, 1) == pytest.approx(scores.log_probability(2, 1))
    assert scores.home_rates == pytest.approx(before[0])
    assert scores.away_rates == pytest.approx(before[1])


def test_future_lineup_does_not_change_earlier_continuity():
    matches, rows = [], []
    start = date(2025, 8, 1)
    for index in range(10):
        away = f"away-{index}"
        match_id = fixture_id("eng-premier-league", "2025-2026", "home", away)
        fixture = Fixture(
            match_id,
            "eng-premier-league",
            "2025-2026",
            start + timedelta(days=index),
            "home",
            away,
        )
        matches.append(
            Match(fixture, 1, 0, "a" * 64, index, str(start + timedelta(days=index + 1)))
        )
        for team in ("home", away):
            for player in range(11):
                rows.append(
                    {
                        "match_id": match_id,
                        "team_id": team,
                        "player_id": f"{team}-{player if index < 9 else player + 1}",
                        "minutes": 90,
                        "starts": True,
                    }
                )
    initial = realized_continuity(matches[:9], rows[:-22])
    with_future = realized_continuity(matches, rows)
    key = matches[8].fixture.match_id, "home"
    assert initial[key] == pytest.approx(0.0)
    assert with_future[key] == pytest.approx(initial[key])
