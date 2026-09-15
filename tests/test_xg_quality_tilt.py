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
    with pytest.raises(ValueError, match="Unknown model kind"):
        make_model({"kind": "centered_quality_tilt"})


def test_zero_weight_mixture_likelihood_is_silent():
    from epl_forecast.models.poisson import PoissonMixture
    from epl_forecast.models.quality_tilt_scores import ScoreMixture

    component = PoissonMixture(np.zeros(2), np.eye(2) * 0.05)
    with np.errstate(divide="raise"):
        actual = ScoreMixture([component, component], [1.0, 0.0]).log_probability(1, 2)
    assert actual == pytest.approx(component.log_probability(1, 2))


def test_unit_scale_and_uncalibrated_provider_recover_their_controls(small_history):
    cutoff = small_history[-1].available_on
    rows = observations(small_history)
    base = XGQualityTiltFilter(rows).fit(small_history, cutoff)
    unit = XGQualityTiltFilter(rows, provider_scales={"understat": 1.0}).fit(small_history, cutoff)
    np.testing.assert_array_equal(base.mean, unit.mean)
    np.testing.assert_array_equal(base.covariance, unit.covariance)
    api = [{**r, "provider": "api_football"} for r in rows]
    goals_only = XGQualityTiltFilter().fit(small_history, cutoff)
    waiting = XGQualityTiltFilter(
        api, provider_scales={"api_football": "calibrated"}, calibration_matches=len(rows) + 1
    ).fit(small_history, cutoff)
    np.testing.assert_array_equal(goals_only.mean, waiting.mean)
    np.testing.assert_array_equal(goals_only.covariance, waiting.covariance)
    assert waiting.xg_updates == 0
    assert waiting.scales == {"api_football": None}


def test_provider_scale_equals_unit_scale_on_rescaled_xg(small_history):
    cutoff = small_history[-1].available_on
    scaled = XGQualityTiltFilter(
        observations(small_history), provider_scales={"understat": 0.8}
    ).fit(small_history, cutoff)
    divided = XGQualityTiltFilter(observations(small_history, 1.5 / 0.8, 1.0)).fit(
        small_history, cutoff
    )
    np.testing.assert_allclose(scaled.mean, divided.mean, atol=1e-10)
    np.testing.assert_allclose(scaled.covariance, divided.covariance, atol=1e-10)


def test_calibrated_scale_uses_only_observations_available_at_the_cutoff(small_history):
    rows = [{**r, "provider": "api_football"} for r in observations(small_history)]
    cutoff = small_history[4].available_on
    settings = {"provider_scales": {"api_football": "calibrated"}, "calibration_matches": 1}
    training = [m for m in small_history if m.available_on <= cutoff]
    left = XGQualityTiltFilter(rows, **settings).fit(training, cutoff)
    goals = sum(m.home_goals + m.away_goals for m in training)
    assert left.scales["api_football"] == pytest.approx(2.3 * len(training) / goals)
    later = [
        {**r, "home_xg": 50.0} if m.available_on > cutoff else r
        for r, m in zip(rows, small_history, strict=True)
    ]
    right = XGQualityTiltFilter(later, **settings).fit(training, cutoff)
    assert right.scales == left.scales
    np.testing.assert_array_equal(left.mean, right.mean)


def test_incremental_fit_filters_again_when_the_calibrated_scale_changes(small_history):
    rows = [{**r, "provider": "api_football"} for r in observations(small_history)]
    settings = {"provider_scales": {"api_football": "calibrated"}, "calibration_matches": 1}
    model = XGQualityTiltFilter(rows, **settings)
    for i, match in enumerate(small_history):
        model.fit(small_history[: i + 1], match.available_on)
    batch = XGQualityTiltFilter(rows, **settings).fit(small_history, small_history[-1].available_on)
    assert model.scales == batch.scales
    np.testing.assert_allclose(model.mean, batch.mean, atol=1e-10)
    np.testing.assert_allclose(model.covariance, batch.covariance, atol=1e-10)


def test_calibrated_scale_recovers_a_known_provider_scale():
    from datetime import date

    from epl_forecast.models.xg_observation import ChanceObservation, chance_rows
    from epl_forecast.models.xg_quality_tilt import calibrated_scale

    rng = np.random.default_rng(411)
    log_rates = np.log(rng.uniform(0.6, 2.2, size=(4000, 2)))
    goals, xg = ChanceObservation([], [], 0.2, provider_scale=0.8).sample(log_rates, rng)
    rows = chance_rows(
        {
            "match_id": f"m{i}",
            "provider": "api_football",
            "match_date": "2024-01-01",
            "available_on": "2024-01-02",
            "home_goals": int(goals[i, 0]),
            "away_goals": int(goals[i, 1]),
            "home_xg": float(xg[i, 0]),
            "away_xg": float(xg[i, 1]),
        }
        for i in range(len(goals))
        if not np.any((xg[i] == 0) & (goals[i] > 0))
    )
    estimate = calibrated_scale(rows, "api_football", date(2024, 1, 2))
    assert estimate == pytest.approx(0.8, abs=0.03)
    assert calibrated_scale(rows, "api_football", date(2024, 1, 1)) is None


def test_higher_xg_raises_the_attacking_rate_in_the_calibrated_filter(small_history):
    cutoff = small_history[-1].available_on
    settings = {"provider_scales": {"api_football": "calibrated"}, "calibration_matches": 1}
    low = [{**r, "provider": "api_football"} for r in observations(small_history, 0.9, 0.9)]
    high = [{**r, "home_xg": 2.5} if i % 2 == 0 else r for i, r in enumerate(low)]
    base = XGQualityTiltFilter(low, **settings).fit(small_history, cutoff)
    lifted = XGQualityTiltFilter(high, **settings).fit(small_history, cutoff)
    team = small_history[0].fixture.home_team_id
    season = small_history[-1].fixture.season_id
    lifted_home = [m for i, m in enumerate(small_history) if i % 2 == 0]
    teams = {m.fixture.home_team_id for m in lifted_home}
    assert team in teams
    assert (
        lifted.team_summary(team, season)["attack_log_rate"]
        > base.team_summary(team, season)["attack_log_rate"]
    )
