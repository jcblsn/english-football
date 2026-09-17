from dataclasses import replace
from datetime import timedelta

import numpy as np
import pytest

from epl_forecast.models.centered_quality_tilt import CenteredQualityTiltFilter
from epl_forecast.models.xg_quality_tilt import BayesianXGQualityTilt, XGQualityTiltFilter


def observations(matches, home_xg=1.5, away_xg=0.8):
    return [
        {
            "match_id": m.fixture.match_id,
            "provider": "understat",
            "match_date": str(m.fixture.match_date),
            "available_on": str(m.available_on),
            "home_goals": m.home_goals,
            "away_goals": m.away_goals,
            "home_xg": home_xg,
            "away_xg": away_xg,
        }
        for m in matches
    ]


def test_missing_xg_exactly_preserves_poisson_parent(small_history):
    cutoff = small_history[-1].available_on
    parent = CenteredQualityTiltFilter(dispersion=None).fit(small_history, cutoff)
    model = XGQualityTiltFilter().fit(small_history, cutoff)
    np.testing.assert_allclose(parent.mean, model.mean, atol=1e-11)
    np.testing.assert_allclose(parent.covariance, model.covariance, atol=1e-11)
    assert model.log_evidence == pytest.approx(parent.log_evidence, abs=1e-10)
    assert model.xg_updates == 0


def test_xg_updates_uncertainty_and_rejects_leakage(small_history):
    cutoff = small_history[-1].available_on
    rows = observations(small_history)
    model = XGQualityTiltFilter(rows).fit(small_history, cutoff)
    parent = XGQualityTiltFilter().fit(small_history, cutoff)
    assert model.xg_updates == len(small_history)
    assert np.linalg.norm(model.mean - parent.mean) > 0.01
    assert np.trace(model.covariance) < np.trace(parent.covariance)
    assert np.linalg.eigvalsh(model.covariance).min() > 0
    late = [{**r, "available_on": str(cutoff + timedelta(days=10))} for r in rows]
    skipped = XGQualityTiltFilter(late).fit(small_history, cutoff)
    np.testing.assert_allclose(skipped.mean, parent.mean)
    bad = [{**rows[0], "home_goals": 99}]
    with pytest.raises(ValueError, match="reconcile"):
        XGQualityTiltFilter(bad).fit(small_history, cutoff)
    assert (
        XGQualityTiltFilter(rows).observations[rows[0]["match_id"]][0]
        == small_history[0].fixture.match_date
    )


def test_incremental_fit_and_future_xg_does_not_enter_forecast(small_history):
    rows = observations(small_history)
    model = XGQualityTiltFilter(rows)
    for i, match in enumerate(small_history):
        model.fit(small_history[: i + 1], match.available_on)
    batch = XGQualityTiltFilter(rows).fit(small_history, small_history[-1].available_on)
    np.testing.assert_allclose(model.mean, batch.mean, atol=1e-10)
    cutoff = small_history[4].available_on
    left = XGQualityTiltFilter(rows).fit(small_history[:5], cutoff)
    rows[5:] = [{**r, "home_xg": 50.0} for r in rows[5:]]
    right = XGQualityTiltFilter(rows).fit(small_history[:5], cutoff)
    np.testing.assert_array_equal(left.mean, right.mean)


def test_bayesian_noise_and_evolving_paths(small_history):
    model = BayesianXGQualityTilt(observations(small_history)).fit(
        small_history, small_history[-1].available_on
    )
    assert model.weights.sum() == pytest.approx(1)
    assert not np.allclose(model.weights, model.prior_weights)
    fixture = replace(small_history[0].fixture, match_date=model.as_of + timedelta(days=60))
    expected = model.predict_match(fixture).probabilities
    paths = model.sample_forecast_state(np.random.default_rng(40), 30000)
    home, away = paths.sample_scores(fixture, np.random.default_rng(41))
    actual = np.array([(home > away).mean(), (home == away).mean(), (home < away).mean()])
    np.testing.assert_allclose(actual, expected, atol=0.015)
    assert sum(
        model.team_summary(t, "2020-2021")["tilt"] for t in model.team_index
    ) == pytest.approx(0, abs=1e-14)


def test_canonical_observations_and_factory(small_history):
    from epl_forecast.models import make_model

    spec = {
        "kind": "bayesian_xg_quality_tilt",
        "parameters": {"observations": observations(small_history)},
    }
    model = make_model(spec).fit(small_history, small_history[-1].available_on)
    assert model.fit_diagnostics["xg_matches"] == len(small_history)
    assert model.fit_diagnostics["quality_dynamics"].startswith(
        "Quality = level + form; level random walk, SD 0.08"
    )
    assert not any("M4" in str(v) or "M5" in str(v) for v in model.fit_diagnostics.values())
    with pytest.raises(ValueError, match="Unknown model kind"):
        make_model({"kind": "centered_quality_tilt"})


def test_zero_weight_mixture_likelihood_is_silent():
    from epl_forecast.models.poisson import PoissonMixture
    from epl_forecast.models.quality_tilt_scores import ScoreMixture

    component = PoissonMixture(np.zeros(2), np.eye(2) * 0.05)
    with np.errstate(divide="raise"):
        actual = ScoreMixture([component, component], [1.0, 0.0]).log_probability(1, 2)
    assert actual == pytest.approx(component.log_probability(1, 2))
