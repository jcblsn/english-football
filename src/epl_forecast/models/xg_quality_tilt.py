"""M10 centered team state with joint opportunity-based goals and xG."""

from copy import copy
from types import MappingProxyType

import numpy as np

from epl_forecast.models.centered_quality_tilt import CenteredQualityTiltFilter
from epl_forecast.models.gaussian import likelihood_laplace_update
from epl_forecast.models.quality_tilt import BayesianQualityTilt, ForwardQualityTiltStates
from epl_forecast.models.xg_observation import ChanceObservation, chance_rows

# Quality is a persistent level, a random walk, plus a form deviation that returns to that level.
XG_DYNAMICS = {
    "quality_retention": 1.0,
    "quality_sd": 0.08,
    "form_retention": 0.3,
    "form_sd": 0.07,
    "tilt_retention": 0.5,
    "tilt_sd": 0.07,
    "dispersion": None,
}


class XGQualityTiltFilter(CenteredQualityTiltFilter):
    def __init__(self, observations=(), chance_probability=0.2, **kwargs):
        if kwargs.get("dispersion") is not None:
            raise ValueError("M10 opportunity thinning implies marginal independent Poisson goals")
        kwargs["dispersion"] = None
        self.chance_probability = chance_probability
        ChanceObservation([], [], chance_probability)
        self._observations = chance_rows(observations)
        super().__init__(**kwargs)

    @property
    def observations(self):
        return MappingProxyType(self._observations)

    def _reset(self):
        super()._reset()
        self.xg_updates = 0
        self._daily_xg = np.empty(0)

    def _prepare_observations(self, games):
        values = []
        for match in games:
            row = self.observations.get(match.fixture.match_id)
            if row is not None:
                day, available, home, away, hx, ax = row
                if day != match.fixture.match_date or (home, away) != (
                    match.home_goals,
                    match.away_goals,
                ):
                    raise ValueError("xG does not reconcile with training result")
                # Daily filtering cannot retrofit observations published after this update.
                if available <= match.available_on:
                    values.extend([hx, ax])
                    self.xg_updates += 1
                    continue
            values.extend([np.nan, np.nan])
        self._daily_xg = np.asarray(values)

    def _update(self, design, goals):
        likelihood = ChanceObservation(goals, self._daily_xg, self.chance_probability)
        self.mean, self.covariance, evidence = likelihood_laplace_update(
            self.mean, self.covariance, self.observation_design(design), likelihood
        )
        self.log_evidence += evidence

    def fit(self, matches, as_of):
        super().fit(matches, as_of)
        self.fit_diagnostics.update(
            {
                "observation_model": "Poisson opportunities; Gamma xG; Binomial goals",
                "chance_probability": self.chance_probability,
                "xg_matches": self.xg_updates,
                "xg_availability": "retrospective next-day assumption; late records skipped",
                "quality_dynamics": self.dynamics_description(),
                "goal_marginal": "Poisson goals; joint goals/xG likelihood",
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
            XGQualityTiltFilter(observations, p, quadrature_order=quadrature_order, **dynamics)
            for p in probabilities
        ]
        self.specifications = [{**dynamics, "chance_probability": p} for p in probabilities]

    def fit(self, matches, as_of):
        super().fit(matches, as_of)
        self.fit_diagnostics.update(
            {
                "observation_model": "joint opportunity goals/xG likelihood",
                "xg_matches": self.members[0].xg_updates,
                "noise_uncertainty": "finite noise prior; chronological joint evidence",
                "coordinates": "centered Tilt contrasts and transition-only scoring memory",
            }
        )
        return self

    def sample_forecast_state(self, rng, size=1):
        snapshot = copy(self)
        snapshot.members = [member.population_snapshot() for member in self.members]
        return ForwardQualityTiltStates(snapshot, rng, size)
