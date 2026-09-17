from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pytest

from epl_forecast.models.centered_quality_tilt import CenteredQualityTiltFilter, tilt_coordinates
from epl_forecast.models.quality_tilt import QualityTiltFilter
from epl_forecast.schema import Fixture, fixture_id


@pytest.mark.parametrize("teams", [0, 1, 2, 20, 35])
def test_coordinates_invertible_and_rate_identifiable(teams):
    transform, inverse = tilt_coordinates(teams)
    np.testing.assert_allclose(transform @ inverse, np.eye(len(transform)), atol=2e-15)
    if teams < 2:
        return
    design = []
    for home in range(teams):
        for away in range(teams):
            if home == away:
                continue
            row = np.zeros((2, len(transform)))
            row[:, :2] = [[1, 1], [1, 0]]
            row[:, 2 + 2 * home : 4 + 2 * home] = [[1, 1], [-1, 1]]
            row[:, 2 + 2 * away : 4 + 2 * away] = [[-1, 1], [1, 1]]
            design.extend(row @ inverse)
    design = np.array(design)
    np.testing.assert_allclose(design[:, -1], 0, atol=1e-15)
    if teams >= 3:
        scoring = design[:, [0] + list(range(3, len(transform) - 2, 2))]
        assert np.linalg.matrix_rank(scoring) == teams


@pytest.mark.parametrize("form", [{}, {"form_retention": 0.3, "form_sd": 0.15}])
@pytest.mark.parametrize("dispersion", [None, 20.0])
def test_daily_filter_entries_forecasts_and_paths_equivalent(small_history, dispersion, form):
    original = QualityTiltFilter(dispersion=dispersion, **form)
    centered = CenteredQualityTiltFilter(dispersion=dispersion, **form)
    for i, match in enumerate(small_history):
        cutoff = match.available_on
        history = small_history[: i + 1]
        original.fit(history, cutoff)
        centered.fit(history, cutoff)
        mean, covariance = centered.population_moments()
        np.testing.assert_allclose(mean, original.mean, atol=1e-11)
        np.testing.assert_allclose(covariance, original.covariance, atol=1e-11)
        assert centered.log_evidence == pytest.approx(original.log_evidence, abs=1e-10)
        assert sum(
            centered.team_state(t, "2020-2021").mean[1] for t in centered.team_index
        ) == pytest.approx(0, abs=1e-15)
    fixtures = [replace(small_history[0].fixture, match_date=cutoff + timedelta(days=90))]
    fixtures.append(
        Fixture(
            fixture_id("eng-premier-league", "2021-2022", "a", "entrant"),
            "eng-premier-league",
            "2021-2022",
            date(2021, 8, 1),
            "a",
            "entrant",
        )
    )
    left = original.sample_forecast_state(np.random.default_rng(42), 2000)
    right = centered.sample_forecast_state(np.random.default_rng(42), 2000)
    rng_left, rng_right = np.random.default_rng(82), np.random.default_rng(82)
    for fixture in fixtures:
        for a, b in zip(
            original.forecast_moments(fixture), centered.forecast_moments(fixture), strict=True
        ):
            np.testing.assert_allclose(a, b, atol=1e-11)
        for a, b in zip(
            left.sample_scores(fixture, rng_left),
            right.sample_scores(fixture, rng_right),
            strict=True,
        ):
            np.testing.assert_array_equal(a, b)


def test_native_transition_preserves_scoring_memory(small_history):
    model = CenteredQualityTiltFilter().fit(small_history, small_history[-1].available_on)
    transition, innovation = model.transition_matrices(1.5)
    assert transition[0, -1] == pytest.approx(2 * (model.tilt_retention**1.5 - 1))
    assert np.linalg.matrix_rank(np.array([[1, 0], transition[0, [0, -1]]])) == 2
    assert innovation[0, -1] > 0
    assert np.linalg.eigvalsh(innovation).min() > 0
    with pytest.raises(ValueError, match="backwards"):
        model.transition_matrices(-1)
    before = model.mean.copy(), model.covariance.copy()
    fixture = replace(small_history[0].fixture, match_date=model.as_of + timedelta(days=30))
    model.forecast_moments(fixture)
    np.testing.assert_array_equal(before[0], model.mean)
    np.testing.assert_array_equal(before[1], model.covariance)
