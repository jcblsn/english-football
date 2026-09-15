"""M7 centered team state with joint opportunity-based goals and provider xG."""

from copy import copy
from types import MappingProxyType

import numpy as np

from epl_forecast.models.centered_quality_tilt import CenteredQualityTiltFilter
from epl_forecast.models.gaussian import likelihood_laplace_update
from epl_forecast.models.quality_tilt import BayesianQualityTilt, ForwardQualityTiltStates
from epl_forecast.models.xg_observation import ChanceObservation, chance_rows

XG_DYNAMICS = {
    "quality_retention": 0.85,
    "quality_sd": 0.09,
    "tilt_retention": 0.5,
    "tilt_sd": 0.07,
    "dispersion": None,
}
CALIBRATED = "calibrated"
MIN_CALIBRATION_MATCHES = 100


def calibrated_scale(rows, provider, as_of, minimum=MIN_CALIBRATION_MATCHES):
    """Provider xG per goal over the observations available at the cutoff, or None if too few."""
    eligible = [row for row in rows.values() if row[6] == provider and row[1] <= as_of]
    goals = sum(row[2] + row[3] for row in eligible)
    if len(eligible) < minimum or goals == 0:
        return None
    return sum(row[4] + row[5] for row in eligible) / goals


class XGQualityTiltFilter(CenteredQualityTiltFilter):
    def __init__(
        self,
        observations=(),
        chance_probability=0.2,
        provider_scales=None,
        calibration_matches=MIN_CALIBRATION_MATCHES,
        **kwargs,
    ):
        if kwargs.get("dispersion") is not None:
            raise ValueError("M7 opportunity thinning implies marginal independent Poisson goals")
        kwargs["dispersion"] = None
        self.chance_probability = chance_probability
        ChanceObservation([], [], chance_probability)
        self.provider_scales = dict(provider_scales or {})
        for scale in self.provider_scales.values():
            if scale != CALIBRATED:
                ChanceObservation([], [], chance_probability, scale)
        self.calibration_matches = calibration_matches
        self._observations = chance_rows(observations)
        self.scales = None
        super().__init__(**kwargs)

    @property
    def observations(self):
        return MappingProxyType(self._observations)

    def _reset(self):
        super()._reset()
        self.xg_updates = 0
        self._daily_xg = np.empty(0)
        self._daily_scale = np.empty(0)

    def scales_at(self, as_of):
        providers = sorted({row[6] for row in self._observations.values()})
        return {
            provider: calibrated_scale(
                self._observations, provider, as_of, self.calibration_matches
            )
            if self.provider_scales.get(provider, 1.0) == CALIBRATED
            else float(self.provider_scales.get(provider, 1.0))
            for provider in providers
        }

    def _prepare_observations(self, games):
        values, scales = [], []
        for match in games:
            row = self.observations.get(match.fixture.match_id)
            if row is not None:
                day, available, home, away, hx, ax, provider = row
                if day != match.fixture.match_date or (home, away) != (
                    match.home_goals,
                    match.away_goals,
                ):
                    raise ValueError("xG does not reconcile with training result")
                scale = self.scales[provider]
                # Daily filtering cannot retrofit observations published after this update.
                if available <= match.available_on and scale is not None:
                    values.extend([hx, ax])
                    scales.extend([scale, scale])
                    self.xg_updates += 1
                    continue
            values.extend([np.nan, np.nan])
            scales.extend([1.0, 1.0])
        self._daily_xg, self._daily_scale = np.asarray(values), np.asarray(scales)

    def _update(self, design, goals):
        likelihood = ChanceObservation(
            goals, self._daily_xg, self.chance_probability, self._daily_scale
        )
        self.mean, self.covariance, evidence = likelihood_laplace_update(
            self.mean, self.covariance, self.observation_design(design), likelihood
        )
        self.log_evidence += evidence

    def fit(self, matches, as_of):
        scales = self.scales_at(as_of)
        if scales != self.scales:
            # A new provider scale changes every earlier xG update, so filter again from the start.
            self.as_of = None
        self.scales = scales
        super().fit(matches, as_of)
        self.fit_diagnostics.update(
            {
                "observation_model": "Poisson opportunities; Gamma xG; Binomial goals",
                "chance_probability": self.chance_probability,
                "xg_matches": self.xg_updates,
                "provider_scales": self.scales,
                "xg_availability": "retrospective next-day assumption; late records skipped",
                "equivalence": "M5 dynamics; Poisson goal marginal; joint goals/xG likelihood",
            }
        )
        return self


class BayesianXGQualityTilt(BayesianQualityTilt):
    def __init__(
        self,
        observations=(),
        chance_probabilities=(0.1, 0.2, 0.35),
        prior_weights=None,
        dynamics=None,
        quadrature_order=9,
        provider_scales=None,
        calibration_matches=MIN_CALIBRATION_MATCHES,
    ):
        dynamics = dict(XG_DYNAMICS if dynamics is None else dynamics)
        observations = tuple(observations)
        probabilities = tuple(chance_probabilities)
        if not probabilities or len(set(probabilities)) != len(probabilities):
            raise ValueError("Specify distinct observation-noise probabilities")
        super().__init__(
            specifications=[dict(dynamics) for _ in probabilities],
            prior_weights=prior_weights,
            quadrature_order=quadrature_order,
        )
        self.members = [
            XGQualityTiltFilter(
                observations,
                p,
                provider_scales=provider_scales,
                calibration_matches=calibration_matches,
                quadrature_order=quadrature_order,
                **dynamics,
            )
            for p in probabilities
        ]
        self.specifications = [{**dynamics, "chance_probability": p} for p in probabilities]

    def fit(self, matches, as_of):
        super().fit(matches, as_of)
        self.fit_diagnostics.update(
            {
                "observation_model": "joint opportunity goals/xG likelihood",
                "xg_matches": self.members[0].xg_updates,
                "provider_scales": self.members[0].scales,
                "noise_uncertainty": "finite noise prior; chronological joint evidence",
                "coordinates": "centered Tilt contrasts and transition-only scoring memory",
            }
        )
        return self

    def sample_forecast_state(self, rng, size=1):
        snapshot = copy(self)
        snapshot.members = [member.population_snapshot() for member in self.members]
        return ForwardQualityTiltStates(snapshot, rng, size)
