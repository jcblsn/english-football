from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pytest
from scipy.optimize import minimize

from epl_forecast.models.dynamic import DynamicAttackDefense
from epl_forecast.models.gaussian import score_laplace_update
from epl_forecast.models.poisson import IndependentPoisson
from epl_forecast.models.quality_tilt import BayesianQualityTilt, QualityTiltFilter
from epl_forecast.models.quality_tilt_scores import GammaPoissonMixture, joint_logpmf
from epl_forecast.schema import Fixture, Match, fixture_id

PL = "eng-premier-league"


def test_shared_tempo_probability_and_moments():
    scores = GammaPoissonMixture(np.log([1.8, 1.1]), np.zeros((2, 2)), dispersion=3)
    grid, tail = scores.grid(45)
    assert tail < 1e-10
    assert scores.outcome_probabilities() == pytest.approx(
        [np.tril(grid, -1).sum(), np.trace(grid), np.triu(grid, 1).sum()], abs=1e-10
    )
    assert np.exp(scores.log_probability(2, 1)) == pytest.approx(grid[2, 1])
    h, a = scores.sample(np.random.default_rng(25), 300000)
    assert h.mean() == pytest.approx(1.8, abs=0.015)
    assert h.var() == pytest.approx(1.8 + 1.8**2 / 3, abs=0.04)
    assert np.cov(h, a)[0, 1] == pytest.approx(1.8 * 1.1 / 3, abs=0.025)
    poisson = IndependentPoisson(1.8, 1.1)
    limit = GammaPoissonMixture(np.log([1.8, 1.1]), np.zeros((2, 2)), dispersion=1e6)
    assert limit.outcome_probabilities() == pytest.approx(poisson.outcome_probabilities(), abs=1e-6)


def test_correlated_laplace_matches_direct_optimization_and_evidence_quadrature():
    mean = np.log([1.5, 1.0])
    covariance = np.array([[0.12, 0.03], [0.03, 0.1]])
    precision = np.linalg.inv(covariance)
    goals = np.array([2, 0])
    result = score_laplace_update(mean, covariance, np.eye(2), goals, 5)

    def objective(x):
        d = x - mean
        return 0.5 * d @ precision @ d - joint_logpmf(2, 0, *np.exp(x), 5)

    optimum = minimize(objective, mean, method="BFGS", tol=1e-9)
    assert result[0] == pytest.approx(optimum.x, abs=1e-7)
    assert np.linalg.eigvalsh(result[1]).min() > 0
    exact_evidence = GammaPoissonMixture(mean, covariance, 25, 5).log_probability(2, 0)
    assert result[2] == pytest.approx(exact_evidence, abs=0.005)


def test_reparameterization_preserves_m4_poisson_filter(small_history):
    cutoff = date(2020, 8, 20)
    m4 = DynamicAttackDefense(promotion_performance=False).fit(small_history, cutoff)
    m5 = QualityTiltFilter(
        quality_retention=0.85,
        tilt_retention=0.85,
        quality_sd=0.18 / np.sqrt(2),
        tilt_sd=0.18 / np.sqrt(2),
        annual_league_sd=0.06,
        annual_home_sd=0.06,
        dispersion=None,
    ).fit(small_history, cutoff)
    transform = np.eye(len(m4.mean))
    for index in range(2, len(transform), 2):
        transform[index : index + 2, index : index + 2] = [[0.5, 0.5], [0.5, -0.5]]
    assert m5.mean == pytest.approx(transform @ m4.mean, abs=1e-8)
    assert m5.covariance == pytest.approx(transform @ m4.covariance @ transform.T, abs=1e-8)
    fixture = replace(small_history[0].fixture, match_date=cutoff)
    assert m5.predict_match(fixture).probabilities == pytest.approx(
        m4.predict_match(fixture).probabilities, abs=1e-8
    )


def test_ensemble_incremental_replay_and_prior_weights(small_history):
    specs = [dict(dispersion=4), dict(dispersion=80)]
    model = BayesianQualityTilt(specs, [1, 2]).fit(small_history[:5], date(2020, 8, 6))
    model.fit(small_history, date(2020, 8, 20))
    fresh = BayesianQualityTilt(specs, [1, 2]).fit(small_history, date(2020, 8, 20))
    assert model.weights == pytest.approx(fresh.weights, abs=1e-8)
    assert model.weights.sum() == pytest.approx(1)
    assert not np.allclose(model.weights, model.prior_weights)
    changed = [replace(small_history[0], home_goals=9)] + small_history[1:]
    model.fit(changed, date(2020, 8, 20))
    fresh.fit(changed, date(2020, 8, 20))
    assert model.weights == pytest.approx(fresh.weights)
    with pytest.raises(ValueError, match="unavailable"):
        model.fit(changed, date(2020, 8, 1))


def test_forward_states_match_forecast_at_future_dates_and_do_not_mutate_fit(small_history):
    model = BayesianQualityTilt([dict(dispersion=6), dict(dispersion=30)]).fit(
        small_history, date(2020, 8, 20)
    )
    fixture = replace(small_history[0].fixture, match_date=date(2021, 5, 1))
    saved = model.members[0].mean.copy()
    rng = np.random.default_rng(81)
    states = model.sample_forecast_state(rng, 100000)
    first = replace(fixture, match_date=date(2020, 10, 1))
    states.sample_scores(first, rng)
    h, a = states.sample_scores(fixture, rng)
    assert [np.mean(h > a), np.mean(h == a), np.mean(h < a)] == pytest.approx(
        model.predict_match(fixture).probabilities, abs=0.006
    )
    assert model.members[0].mean == pytest.approx(saved)
    with pytest.raises(ValueError, match="chronological"):
        states.sample_scores(first, rng)
    summary = model.team_summary("a", "2020-2021")
    assert summary["quality_sd"] > 0 and summary["tilt_sd"] > 0


def test_separate_transitions_have_semigroup_property():
    model = QualityTiltFilter()
    a, av = model.transition(0.3, 6)
    b, bv = model.transition(0.7, 6)
    total, variance = model.transition(1, 6)
    assert a * b == pytest.approx(total)
    assert av * b**2 + bv == pytest.approx(variance)
    assert total[2] != total[3]
    assert variance[2] != variance[3]


def test_direct_component_sampling_uses_quality_tilt_coordinates(small_history):
    model = QualityTiltFilter().fit(small_history, date(2020, 8, 20))
    fixture = replace(small_history[0].fixture, match_date=date(2021, 4, 1))
    rng = np.random.default_rng(717)
    h, a = model.sample_forecast_state(rng, 80000).sample_scores(fixture, rng)
    assert [np.mean(h > a), np.mean(h == a), np.mean(h < a)] == pytest.approx(
        model.predict_match(fixture).probabilities, abs=0.008
    )


def test_exported_variance_decomposition_and_tail_diagnostics():
    from epl_forecast.models.quality_tilt_scores import ScoreMixture, score_diagnostics

    components = [
        GammaPoissonMixture(np.log(rates), np.zeros((2, 2)), dispersion=5)
        for rates in ([1.0, 2.0], [3.0, 1.0])
    ]
    scores = ScoreMixture(components, [0.25, 0.75])
    moments = scores.uncertainty_components()
    means = np.array([[1.0, 2.0], [3.0, 1.0]])
    mean = np.array([0.25, 0.75]) @ means
    centered = means - mean
    state = (centered.T * [0.25, 0.75]) @ centered
    tempo = (means.T * [0.25, 0.75]) @ means / 5
    assert moments["state_rate_covariance"] == pytest.approx(state)
    assert moments["total_score_covariance"] == pytest.approx(state + tempo + np.diag(mean))
    grid, _ = scores.grid(60)
    diagnostics = score_diagnostics(scores)
    assert diagnostics["p_scoreless"] == pytest.approx(grid[0, 0])
    assert diagnostics["p_both_score"] == pytest.approx(grid[1:, 1:].sum(), abs=1e-10)
    assert diagnostics["p_total_goals_ge6"] == pytest.approx(
        grid[np.indices(grid.shape).sum(axis=0) >= 6].sum(), abs=1e-10
    )


def test_negligible_form_reproduces_single_quality_process(small_history):
    cutoff = small_history[-1].available_on
    single = QualityTiltFilter(quality_retention=1.0, dispersion=None).fit(small_history, cutoff)
    split = QualityTiltFilter(
        quality_retention=1.0, form_retention=0.5, form_sd=1e-7, dispersion=None
    ).fit(small_history, cutoff)
    assert split.team_dimensions == 3 and len(split.mean) == 2 + 3 * len(split.team_index)
    assert split.log_evidence == pytest.approx(single.log_evidence, abs=1e-8)
    np.testing.assert_allclose(split.attack, single.attack, atol=1e-8)
    fixture = replace(small_history[0].fixture, match_date=cutoff + timedelta(days=40))
    for a, b in zip(single.forecast_moments(fixture), split.forecast_moments(fixture), strict=True):
        np.testing.assert_allclose(a, b, atol=1e-8)
    summary = split.team_summary("a", fixture.season_id)
    assert summary["quality"] == pytest.approx(summary["quality_level"] + summary["quality_form"])
    assert summary["quality_form_sd"] < 1e-6


def test_form_returns_to_the_club_level(small_history):
    model = QualityTiltFilter(
        quality_retention=1.0, form_retention=0.2, form_sd=0.2, dispersion=None
    ).fit(small_history, small_history[-1].available_on)
    summary = model.team_summary("a", small_history[-1].fixture.season_id)
    assert summary["quality_sd"] ** 2 == pytest.approx(
        summary["quality_level_sd"] ** 2
        + summary["quality_form_sd"] ** 2
        + 2 * summary["quality_level_form_covariance"]
    )
    assert summary["quality_level_form_covariance"] < 0
    decay, variance = model.team_transition(1.0)
    np.testing.assert_allclose(decay, [1.0, model.tilt_retention, 0.2])
    assert variance[2] == pytest.approx(0.2**2)
    with pytest.raises(ValueError, match="both"):
        QualityTiltFilter(form_sd=0.1)
    with pytest.raises(ValueError, match="Form retention"):
        QualityTiltFilter(form_retention=1.0, form_sd=0.1)


def rotating_seasons(first, last, clubs=20, turnover=3):
    """A Premier League where three clubs leave and three new clubs enter each season."""
    rng = np.random.default_rng(7)
    matches = []
    for year in range(first, last + 1):
        season = f"{year}-{year + 1}"
        offset = turnover * (year - first)
        teams = [f"club-{i}" for i in range(offset, offset + clubs)]
        pairs = [(h, a) for h in teams for a in teams if h != a]
        for index, (home, away) in enumerate(pairs):
            day = date(year, 8, 1) + timedelta(days=index // 10)
            fixture = Fixture(fixture_id(PL, season, home, away), PL, season, day, home, away)
            matches.append(Match(fixture, int(rng.poisson(1.5)), int(rng.poisson(1.2))))
    return matches


def common_quality(model, teams):
    """Posterior mean and SD of the mean Quality of these clubs, in population coordinates."""
    vector = np.zeros(len(model.mean))
    for team in teams:
        block = model._team_slice(team)
        vector[block] = model.team_loading[0] / len(teams)
    return vector @ model.mean, np.sqrt(vector @ model.covariance @ vector)


def test_common_quality_direction_does_not_change_forecasts_between_fitted_clubs(small_history):
    cutoff = small_history[-1].available_on
    model = QualityTiltFilter(
        quality_retention=1.0, form_retention=0.3, form_sd=0.07, dispersion=None
    ).fit(small_history, cutoff)
    fixture = replace(small_history[0].fixture, match_date=cutoff + timedelta(days=5))
    before = model.forecast_moments(fixture)
    direction = np.zeros(len(model.mean))
    for team in model.team_index:
        direction[model._team_slice(team)] = model.team_loading[0]
    model.mean = model.mean + 0.3 * direction
    model.covariance = model.covariance + 0.05 * np.outer(direction, direction)
    for a, b in zip(before, model.forecast_moments(fixture), strict=True):
        np.testing.assert_allclose(a, b, atol=1e-12)


def test_entrants_keep_the_common_quality_uncertainty_bounded():
    history = rotating_seasons(2014, 2021)
    model = QualityTiltFilter(
        quality_retention=1.0,
        quality_sd=0.08,
        form_retention=0.3,
        form_sd=0.07,
        tilt_retention=0.5,
        tilt_sd=0.07,
        dispersion=None,
    )
    spread = {}
    for year in (2016, 2021):
        season = f"{year}-{year + 1}"
        cutoff = date(year, 7, 31)
        model.fit([m for m in history if m.available_on <= cutoff], cutoff)
        continuing = [
            t
            for t in {m.fixture.home_team_id for m in history if m.fixture.season_id == season}
            if model._uses_fitted_state(t, season)
        ]
        spread[year] = common_quality(model, continuing)[1]
    # The zero-referenced entry priors fix the frame. Without entrants, this SD increases each season.
    assert spread[2021] < spread[2016]
