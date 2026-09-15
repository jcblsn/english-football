import numpy as np
import pytest
from scipy.integrate import quad
from scipy.stats import poisson

from epl_forecast.models.xg_observation import ChanceObservation


@pytest.mark.parametrize("goals", [0, 1, 4])
@pytest.mark.parametrize("p", [0.1, 0.35])
def test_integrating_xg_recovers_poisson_goal_marginal(goals, p):
    rate = 1.4

    def density(x):
        return np.exp(ChanceObservation([goals], [x], p)(np.log([rate]))[0])

    mass = quad(density, 0, np.inf, epsabs=1e-9)[0]
    if goals == 0:
        mass += np.exp(-rate / p)
    assert mass == pytest.approx(poisson.pmf(goals, rate), abs=1e-8)


@pytest.mark.parametrize("xg", [np.nan, 0.0, 0.001, 1.3, 8.0])
def test_likelihood_derivatives(xg):
    model = ChanceObservation([0], [xg], 0.2)
    eta, step = np.array([-0.3]), 1e-5
    value, score, curvature = model(eta)
    plus, minus = model(eta + step), model(eta - step)
    assert score[0] == pytest.approx((plus[0] - minus[0]) / (2 * step), abs=1e-8)
    assert curvature[0, 0] == pytest.approx(-(plus[1][0] - minus[1][0]) / (2 * step), abs=1e-8)
    assert np.isfinite(value)


def test_series_extends_for_large_xg_and_rate():
    model = ChanceObservation([12], [35], 0.1)
    value, score, curvature = model(np.log([30]))
    assert np.isfinite(value) and np.isfinite(score).all() and np.isfinite(curvature).all()
    assert len(model.terms[0][0]) == 128


def test_opportunity_generative_moments():
    rate, p, size = 1.5, 0.2, 300000
    model = ChanceObservation([], [], p)
    goals, xg = model.sample(np.full(size, np.log(rate)), np.random.default_rng(409))
    assert goals.mean() == pytest.approx(rate, abs=0.015)
    assert goals.var() == pytest.approx(rate, abs=0.025)
    assert xg.mean() == pytest.approx(rate, abs=0.01)
    assert xg.var() == pytest.approx(2 * p * rate, abs=0.012)
    assert np.cov(goals, xg)[0, 1] == pytest.approx(p * rate, abs=0.01)


def test_zero_atom_and_invalid_inputs():
    value, score, curvature = ChanceObservation([0], [0], 0.2)(np.log([1.4]))
    assert value == pytest.approx(-7)
    assert score[0] == pytest.approx(-7)
    assert curvature[0, 0] == pytest.approx(7)
    with pytest.raises(ValueError, match="zero xG"):
        ChanceObservation([1], [0], 0.2)
    with pytest.raises(ValueError, match="Goals"):
        ChanceObservation([0.5], [1], 0.2)
    with pytest.raises(ValueError, match="xG"):
        ChanceObservation([1], [np.inf], 0.2)


def test_unit_provider_scale_is_the_current_likelihood():
    goals, xg, eta = [0, 2, 1, 3], [np.nan, 1.7, 0.0, 2.4], np.log([1.1, 1.6, 0.4, 2.0])
    goals[2] = 0
    base, scaled = (
        ChanceObservation(goals, xg, 0.2)(eta),
        ChanceObservation(goals, xg, 0.2, provider_scale=1.0)(eta),
    )
    assert base[0] == scaled[0]
    np.testing.assert_array_equal(base[1], scaled[1])
    np.testing.assert_array_equal(base[2], scaled[2])


@pytest.mark.parametrize("scale", [0.7, 1.3])
def test_provider_scale_rescales_the_xg_measurement(scale):
    goals, xg, eta = [0, 2, 1], [np.nan, 1.7, 0.8], np.log([1.1, 1.6, 0.9])
    scaled = ChanceObservation(goals, xg, 0.25, provider_scale=scale)(eta)
    unscaled = ChanceObservation(goals, np.asarray(xg) / scale, 0.25)(eta)
    observed = sum(not np.isnan(x) for x in xg)
    assert scaled[0] == pytest.approx(unscaled[0] - observed * np.log(scale), abs=1e-10)
    np.testing.assert_allclose(scaled[1], unscaled[1], atol=1e-10)
    np.testing.assert_allclose(scaled[2], unscaled[2], atol=1e-10)


@pytest.mark.parametrize("goals", [0, 3])
def test_scaled_xg_integrates_to_the_poisson_goal_marginal(goals):
    rate, p, scale = 1.4, 0.2, 0.8

    def density(x):
        return np.exp(ChanceObservation([goals], [x], p, scale)(np.log([rate]))[0])

    mass = quad(density, 0, np.inf, epsabs=1e-9)[0]
    if goals == 0:
        mass += np.exp(-rate / p)
    assert mass == pytest.approx(poisson.pmf(goals, rate), abs=1e-8)


def test_scaled_generative_mean_and_invalid_scale():
    rate, p, scale, size = 1.5, 0.2, 0.85, 300000
    model = ChanceObservation([], [], p, provider_scale=scale)
    goals, xg = model.sample(np.full(size, np.log(rate)), np.random.default_rng(410))
    assert goals.mean() == pytest.approx(rate, abs=0.015)
    assert xg.mean() == pytest.approx(scale * rate, abs=0.01)
    for bad in (0.0, -1.0, np.inf, np.nan):
        with pytest.raises(ValueError, match="Provider scale"):
            ChanceObservation([1], [1], 0.2, provider_scale=bad)
