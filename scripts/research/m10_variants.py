"""Candidates of the M10 pre-merge checks, as subclasses of the product M10 model.

E1 gives an entrant the entry-prior Quality variance in total, split between level and form. S1 and
S2 add a level innovation at the first match of a continuing club in a new season. The product code
does not change; `install` replaces the product model kind in this process only.
"""

import numpy as np

from epl_forecast import models
from epl_forecast.models.promotion import TeamPrior
from epl_forecast.models.quality_tilt import ForwardQualityTiltStates, QualityTiltFilter
from epl_forecast.models.xg_quality_tilt import (
    XG_DYNAMICS,
    BayesianXGQualityTilt,
    XGQualityTiltFilter,
)

M7_DYNAMICS = {
    "quality_retention": 0.85,
    "quality_sd": 0.09,
    "tilt_retention": 0.5,
    "tilt_sd": 0.07,
    "dispersion": None,
}
CANDIDATES = {
    "M7": {"dynamics": M7_DYNAMICS},
    "M10": {"dynamics": dict(XG_DYNAMICS)},
    "E1": {"dynamics": dict(XG_DYNAMICS), "entry_total": True},
    "S1": {"dynamics": dict(XG_DYNAMICS), "close_season_sd": 0.08},
    "S2": {
        "dynamics": {**XG_DYNAMICS, "quality_sd": 0.08 / np.sqrt(2)},
        "close_season_sd": 0.08 / np.sqrt(2),
    },
}


class VariantMixin:
    entry_total = False
    close_season_sd = 0.0

    def _entry_prior(self, team, season, as_of):
        prior = super()._entry_prior(team, season, as_of)
        if not self.entry_total or not self.form_sd:
            return prior
        covariance = prior.covariance.copy()
        form = min(self.form_stationary_variance(), covariance[0, 0] / 2)
        covariance[2, 2] = form
        covariance[0, 0] -= form
        limit = 0.999 * np.sqrt(covariance[0, 0] * covariance[1, 1])
        covariance[0, 1] = covariance[1, 0] = np.clip(covariance[0, 1], -limit, limit)
        return TeamPrior(prior.mean, covariance, prior.source)

    def _ensure_team(self, team, season, day, competition=None):
        continuing = (
            self.close_season_sd
            and team in self.team_index
            and self._last_season.get(team) != season
            and not self._entry_replaces_state(team, season, day)
        )
        super()._ensure_team(team, season, day, competition)
        if continuing:
            # The level slot is not transformed by the centered Tilt coordinates.
            level = self._team_slice(team).start
            self.covariance[level, level] += self.close_season_sd**2


class VariantPopulation(VariantMixin, QualityTiltFilter):
    pass


class VariantFilter(VariantMixin, XGQualityTiltFilter):
    def __init__(self, *args, entry_total=False, close_season_sd=0.0, **kwargs):
        self.entry_total, self.close_season_sd = entry_total, close_season_sd
        super().__init__(*args, **kwargs)

    def _population_class(self):
        return VariantPopulation

    def population_snapshot(self):
        snapshot = super().population_snapshot()
        snapshot.entry_total, snapshot.close_season_sd = self.entry_total, self.close_season_sd
        return snapshot


class VariantForwardStates(ForwardQualityTiltStates):
    def _group_rates(self, group, fixture, rng):
        model, entries = group[1], group[4]
        if model.close_season_sd:
            for team in (fixture.home_team_id, fixture.away_team_id):
                key = "close season", team, fixture.season_id
                if (
                    key not in entries
                    and model._uses_fitted_state(team, fixture.season_id)
                    and model._last_season.get(team) != fixture.season_id
                ):
                    level = model._team_slice(team).start
                    group[2][:, level] += model.close_season_sd * self.rng.standard_normal(
                        len(group[0])
                    )
                    entries[key] = None
        return super()._group_rates(group, fixture, rng)


class BayesianVariant(BayesianXGQualityTilt):
    def __init__(
        self,
        observations=(),
        chance_probabilities=(0.1, 0.2, 0.35),
        prior_weights=None,
        dynamics=None,
        quadrature_order=9,
        entry_total=False,
        close_season_sd=0.0,
    ):
        super().__init__(
            observations, chance_probabilities, prior_weights, dynamics, quadrature_order
        )
        dynamics = dict(XG_DYNAMICS if dynamics is None else dynamics)
        self.members = [
            VariantFilter(
                observations,
                p,
                quadrature_order=quadrature_order,
                entry_total=entry_total,
                close_season_sd=close_season_sd,
                **dynamics,
            )
            for p in chance_probabilities
        ]

    def sample_forecast_state(self, rng, size=1):
        from copy import copy

        snapshot = copy(self)
        snapshot.members = [member.population_snapshot() for member in self.members]
        return VariantForwardStates(snapshot, rng, size)


def install():
    models.MODEL_TYPES["bayesian_xg_quality_tilt"] = BayesianVariant
