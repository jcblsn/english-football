"""Centered team Tilt with an explicit, forecast-equivalent scoring transition."""

from copy import copy
from functools import lru_cache

import numpy as np
from scipy.linalg import helmert

from epl_forecast.models.gaussian import score_laplace_update
from epl_forecast.models.promotion import TeamPrior
from epl_forecast.models.quality_tilt import QualityTiltFilter


@lru_cache(maxsize=128)
def tilt_coordinates(teams, absorption=(2.0, 0.0), team_dimensions=2):
    """Map population coordinates to league slots, club slots, Tilt contrasts and scoring memory.

    Every club Tilt enters both teams' log rates with the same sign, so the
    population mean of Tilt is a scoring level. `absorption` gives the coefficient
    with which that mean enters each slot of the leading league block, and the
    corresponding slot takes ownership of it here. Tilt is the second slot of each club.
    """
    if type(teams) is not int or teams < 0:
        raise ValueError("Team count must be a nonnegative integer")
    league = len(absorption)
    if league < 2 or league % 2:
        raise ValueError("The leading league block needs an even number of slots")
    size = league + team_dimensions * teams
    transform, inverse = np.eye(size), np.eye(size)
    if teams:
        indices = np.arange(league + 1, size, team_dimensions)
        transform[np.ix_(indices, indices)] = np.vstack(
            [helmert(teams), np.full((1, teams), 1 / teams)]
        )
        inverse[np.ix_(indices, indices)] = np.column_stack([helmert(teams).T, np.ones(teams)])
        for slot, coefficient in enumerate(absorption):
            if coefficient:
                transform[slot, indices] = coefficient / teams
                inverse[slot, indices[-1]] = -coefficient
    transform.setflags(write=False)
    inverse.setflags(write=False)
    return transform, inverse


class CenteredQualityTiltFilter(QualityTiltFilter):
    """Infer centered contrasts; the final Tilt slot is temporal scoring memory.

    Memory has no direct coefficient in any observed match rate. Its mean
    reversion drives future scoring level, preserving the original M5 process.
    """

    def __init__(self, independent_poisson=False, **kwargs):
        if independent_poisson:
            kwargs["dispersion"] = None
        super().__init__(**kwargs)

    def _mean_tilt_absorption(self):
        """Which league slots own the population mean of club Tilt.

        Every club Tilt enters both rates once, so the shared scoring level owns
        the whole mean unless a subclass loads Tilt differently by division.
        """
        return (2.0,) + (0.0,) * (self.league_dimensions - 1)

    def _coordinates(self):
        return tilt_coordinates(
            len(self.team_index), self._mean_tilt_absorption(), self.team_dimensions
        )

    def _memory_index(self):
        """The Tilt slot of the last club holds the population mean of Tilt."""
        return (
            self.league_dimensions
            + self.team_dimensions * len(self.team_index)
            - (self.team_dimensions - 1)
        )

    def population_moments(self):
        _, inverse = self._coordinates()
        return inverse @ self.mean, inverse @ self.covariance @ inverse.T

    def _population_class(self):
        """The uncentered filter these coordinates are a transformation of."""
        return QualityTiltFilter

    def population_snapshot(self):
        snapshot = self._population_class()()
        snapshot.__dict__.update(self.__dict__)
        snapshot.mean, snapshot.covariance = self.population_moments()
        snapshot.team_index = self.team_index.copy()
        snapshot._last_season = self._last_season.copy()
        snapshot.entry_priors = self.entry_priors.copy()
        return snapshot

    def _ensure_team(self, team, season, day, competition=None):
        if self._last_season.get(team) == season:
            return
        self.mean, self.covariance = self.population_moments()
        super()._ensure_team(team, season, day, competition)
        transform, _ = self._coordinates()
        self.mean = transform @ self.mean
        self.covariance = transform @ self.covariance @ transform.T

    def transition_matrices(self, years):
        transform, inverse = self._coordinates()
        decay, variance = super().transition(years, len(self.mean))
        return (transform * decay) @ inverse, (transform * variance) @ transform.T

    def _advance(self, day):
        if self._state_date is not None:
            transition, innovation = self.transition_matrices(
                (day - self._state_date).days / 365.25
            )
            self.mean = transition @ self.mean
            self.covariance = transition @ self.covariance @ transition.T + innovation
            self.covariance = (self.covariance + self.covariance.T) / 2
        self._state_date = day

    def observation_design(self, population_design):
        return population_design @ self._coordinates()[1]

    def _update(self, design, goals):
        self.mean, self.covariance, evidence = score_laplace_update(
            self.mean, self.covariance, self.observation_design(design), goals, self.dispersion
        )
        self.log_evidence += evidence

    def fit(self, matches, as_of):
        super().fit(matches, as_of)
        self.fit_diagnostics.update(
            {
                "coordinates": "league scoring level plus orthonormal centered team Tilt contrasts",
                "scoring_memory": "mean-reverting common Tilt; transition-only rate loading",
                "centering_population": list(self.team_index),
                "inference": "daily joint Laplace Gaussian filter in centered coordinates",
                "equivalence": "exact linear transformation of M5 priors, dynamics and likelihood",
            }
        )
        return self

    def _club_quality(self):
        blocks = self.mean[self.league_dimensions :].reshape(-1, self.team_dimensions)
        return blocks @ self.team_loading[0]

    def _centered_tilt_map(self):
        n = len(self.team_index)
        design = np.zeros((n, len(self.mean)))
        if n > 1:
            first = self.league_dimensions + 1
            design[:, first : self._memory_index() : self.team_dimensions] = helmert(n).T
        return design

    @property
    def attack(self):
        return self._club_quality() + self._centered_tilt_map() @ self.mean

    @property
    def defense(self):
        return self._club_quality() - self._centered_tilt_map() @ self.mean

    def team_state(self, team, season):
        if self.as_of is None:
            raise ValueError("Fit the model before prediction")
        if self._uses_fitted_state(team, season):
            index = self.team_index[team]
            block = self._team_slice(team)
            design = np.eye(len(self.mean))[block]
            design[1] = self._centered_tilt_map()[index]
            source = self.entry_priors.get((team, season))
            return TeamPrior(
                design @ self.mean,
                design @ self.covariance @ design.T,
                source.source if source is not None else "previous league state",
            )
        prior = self._entry_prior(team, season, self.as_of)
        mean, covariance = prior.mean.copy(), prior.covariance.copy()
        if self.team_index:
            memory = self._memory_index()
            mean[1] -= self.mean[memory]
            covariance[1, 1] += self.covariance[memory, memory]
        return TeamPrior(mean, covariance, prior.source)

    def forecast_moments(self, fixture):
        self.validate_fixture(fixture)
        snapshot = copy(self)
        snapshot.mean, snapshot.covariance = self.mean.copy(), self.covariance.copy()
        snapshot.team_index = self.team_index.copy()
        snapshot._last_season = self._last_season.copy()
        snapshot.entry_priors = self.entry_priors.copy()
        for team in (fixture.home_team_id, fixture.away_team_id):
            snapshot._ensure_team(team, fixture.season_id, self.as_of, fixture.competition_id)
        snapshot._advance(fixture.match_date)
        design = np.zeros((2, len(snapshot.mean)))
        design[:, : self.league_dimensions] = self._league_design(fixture)
        for team, transform in zip(
            (fixture.home_team_id, fixture.away_team_id),
            self._team_transforms(fixture),
            strict=True,
        ):
            design[:, snapshot._team_slice(team)] = transform
        design = snapshot.observation_design(design)
        return design @ snapshot.mean, design @ snapshot.covariance @ design.T

    def sample_forecast_state(self, rng, size=1):
        return self.population_snapshot().sample_forecast_state(rng, size)
