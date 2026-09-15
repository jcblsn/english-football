from collections import Counter
from copy import copy
from datetime import date
from itertools import groupby
from typing import Self

import numpy as np

from epl_forecast.competitions import ENTRY_SOURCE_COMPETITION_IDS
from epl_forecast.models.base import Forecast
from epl_forecast.models.baselines import BaseModel
from epl_forecast.models.entry_prior import EntryPriorModel
from epl_forecast.models.gaussian import poisson_laplace_update
from epl_forecast.models.poisson import IndependentPoisson, PoissonMixture
from epl_forecast.models.promotion import (
    PL,
    PromotionBridge,
    RelegationBridge,
    TeamPrior,
    completed_seasons,
)
from epl_forecast.schema import Fixture, Match

RELEGATION_ENTRY = ("retained", "generic", "mapped")


class DynamicAttackDefense(BaseModel):
    """The state holds a leading league block, then two slots per club.

    One generic entry rule covers every division boundary: a club that played the
    forecast competition last season carries its filtered state, and a club
    arriving from anywhere else is described by a transition-aware entry prior.
    Setting `entry_prior` to None restores the earlier split rule, where a
    promoted club used the Championship bridge and every other entrant kept
    whatever target-division state it last held, however old.
    """

    league_dimensions = 2
    relegation_entry = "retained"
    entry_prior = "memory"
    entry_prior_label = "season"

    def __init__(
        self,
        annual_retention: float = 0.85,
        annual_team_sd: float = 0.18,
        annual_league_sd: float = 0.06,
        initial_team_sd: float = 0.4,
        quadrature_order: int = 9,
        promotion_performance: bool = True,
    ) -> None:
        super().__init__()
        if not np.isfinite(annual_retention) or not 0 < annual_retention <= 1:
            raise ValueError("annual_retention must be in (0, 1]")
        for value in (annual_team_sd, annual_league_sd, initial_team_sd):
            if not np.isfinite(value) or value <= 0:
                raise ValueError("State standard deviations must be finite and positive")
        if type(quadrature_order) is not int or quadrature_order < 2:
            raise ValueError("quadrature_order must be an integer of at least two")
        self.annual_retention = annual_retention
        self.annual_team_sd = annual_team_sd
        self.annual_league_sd = annual_league_sd
        self.initial_team_sd = initial_team_sd
        self.quadrature_order = quadrature_order
        self.primary_competition = PL
        self.promotion_performance = promotion_performance
        self._reset()

    def _reset(self) -> None:
        self.as_of = None
        self._state_date = None
        self._history = []
        self._seasons = {}
        self._bridges = {}
        self._entry_models = {}
        self.team_index = {}
        self._last_season = {}
        self.entry_priors = {}
        self.appearances = Counter()
        mean, variance = self.league_prior()
        if len(mean) != self.league_dimensions or len(variance) != self.league_dimensions:
            raise ValueError("The league prior must cover every leading state dimension")
        self.mean, self.covariance = np.asarray(mean, dtype=float), np.diag(variance)
        self.updates = 0

    def league_prior(self) -> tuple[np.ndarray, np.ndarray]:
        """Prior mean and variance for each slot of the leading league block."""
        return np.array([np.log(1.2), np.log(1.3)]), np.array([0.25**2, 0.25**2])

    def _team_slice(self, team: str) -> slice:
        index = self.league_dimensions + 2 * self.team_index[team]
        return slice(index, index + 2)

    def _league_design(self, fixture_or_match) -> np.ndarray:
        """Rows are home and away log rates; columns are the leading league block."""
        return np.array([[1.0, 1.0], [1.0, 0.0]])

    def _bridge(self, season: str, as_of: date, kind=PromotionBridge):
        available = {
            key: rows
            for key, rows in self._seasons.items()
            if key[1] < season and rows[-1].available_on <= as_of
        }
        key = kind.__name__, season, tuple(sorted(available))
        if key not in self._bridges:
            self._bridges[key] = kind(
                [m for rows in available.values() for m in rows], as_of, season
            )
        return self._bridges[key]

    def _boundary_bridge(self, season: str, as_of: date):
        """The division boundary a club can cross into this competition, when one is modeled.

        Clubs enter the Premier League from the Championship. The reverse
        boundary is off by default, so a relegated club keeps whatever
        Championship state it last had.
        """
        if self.primary_competition == PL:
            return self._bridge(season, as_of, PromotionBridge)
        if self.relegation_entry == "retained":
            return None
        return self._bridge(season, as_of, RelegationBridge)

    def _entry_model(self, season: str, as_of: date) -> EntryPriorModel:
        """The transition-aware entry rule, trained only on seasons already finished."""
        available = {
            key: rows
            for key, rows in self._seasons.items()
            if key[1] < season and rows[-1].available_on <= as_of
        }
        key = season, tuple(sorted(available)), self.entry_prior, self.entry_prior_label
        if key not in self._entry_models:
            self._entry_models[key] = EntryPriorModel(
                available,
                self.primary_competition,
                season,
                as_of,
                self.entry_prior,
                self.initial_team_sd,
                label=self.entry_prior_label,
            )
        return self._entry_models[key]

    def _population_prior(self) -> TeamPrior:
        return TeamPrior(np.zeros(2), np.eye(2) * self.initial_team_sd**2, "league population")

    def _entry_replaces_state(self, team: str, season: str, as_of: date) -> bool:
        """Whether this club crosses a boundary into the division rather than continuing in it."""
        if self.entry_prior is not None:
            return self._entry_model(season, as_of).features(team) is not None
        bridge = self._boundary_bridge(season, as_of)
        return bridge is not None and bridge.prior(team) is not None

    def _entry_prior(self, team: str, season: str, as_of: date) -> TeamPrior:
        if self.entry_prior is not None:
            prior = self._entry_model(season, as_of).prior(team)
            return prior if prior is not None else self._population_prior()
        bridge = self._boundary_bridge(season, as_of)
        if bridge is None:
            return self._population_prior()
        performance = (
            self.promotion_performance
            if self.primary_competition == PL
            else self.relegation_entry == "mapped"
        )
        prior = bridge.prior(team, performance)
        return prior if prior is not None else self._population_prior()

    def _ensure_team(self, team: str, season: str, day: date, competition=None) -> None:
        if self._last_season.get(team) == season:
            return
        prior = self._entry_prior(team, season, day)
        if team not in self.team_index:
            index = len(self.team_index)
            self.team_index[team] = index
            self.mean = np.r_[self.mean, prior.mean]
            self.covariance = np.pad(self.covariance, ((0, 2), (0, 2)))
            self.covariance[-2:, -2:] = prior.covariance
        elif self._entry_replaces_state(team, season, day):
            index = self.league_dimensions + 2 * self.team_index[team]
            self.mean[index : index + 2] = prior.mean
            self.covariance[index : index + 2, :] = 0
            self.covariance[:, index : index + 2] = 0
            self.covariance[index : index + 2, index : index + 2] = prior.covariance
        else:
            index = self.league_dimensions + 2 * self.team_index[team]
            prior = TeamPrior(
                self.mean[index : index + 2].copy(),
                self.covariance[index : index + 2, index : index + 2].copy(),
                "previous league state",
            )
        self.entry_priors[team, season] = prior
        self._last_season[team] = season

    def _advance(self, day: date) -> None:
        if self._state_date is not None:
            years = (day - self._state_date).days / 365.25
            if years < 0:
                raise ValueError("Cannot evolve a state backwards")
            factor = self.annual_retention**years
            team_variance = self.annual_team_sd**2 * (
                years
                if self.annual_retention == 1
                else (1 - factor**2) / (1 - self.annual_retention**2)
            )
            leading = self.league_dimensions
            decay = np.r_[np.ones(leading), np.full(len(self.mean) - leading, factor)]
            self.mean *= decay
            self.covariance *= np.outer(decay, decay)
            self.covariance += np.diag(
                np.r_[
                    np.full(leading, self.annual_league_sd**2 * years),
                    np.full(len(self.mean) - leading, team_variance),
                ]
            )
        self._state_date = day

    def fit(self, matches: list[Match], as_of: date) -> Self:
        if not matches:
            raise ValueError("Training set is empty")
        if any(m.available_on > as_of for m in matches):
            raise ValueError("Training contains a result unavailable at the forecast cutoff")
        if any(m.fixture.competition_id not in ENTRY_SOURCE_COMPETITION_IDS for m in matches):
            raise ValueError("M4 supports evidence from the English entry-source divisions")
        if len({m.fixture.match_id for m in matches}) != len(matches):
            raise ValueError("Duplicate training matches")
        ordered = sorted(matches, key=lambda m: (m.fixture.match_date, m.fixture.match_id))
        if not any(m.fixture.competition_id == self.primary_competition for m in ordered):
            raise ValueError("Dynamic model requires results in its forecast competition")
        if (
            self.as_of is None
            or as_of < self.as_of
            or ordered[: len(self._history)] != self._history
        ):
            self._reset()
        new = [
            m
            for m in ordered[len(self._history) :]
            if m.fixture.competition_id == self.primary_competition
        ]
        self._seasons = completed_seasons(ordered, as_of)
        try:
            for day, games in groupby(new, key=lambda m: m.fixture.match_date):
                games = list(games)
                self._advance(day)
                for match in games:
                    for team in (match.fixture.home_team_id, match.fixture.away_team_id):
                        self._ensure_team(
                            team, match.fixture.season_id, day, match.fixture.competition_id
                        )
                self._prepare_observations(games)
                design = np.zeros((2 * len(games), len(self.mean)))
                goals = []
                for row, match in enumerate(games):
                    design[2 * row : 2 * row + 2, : self.league_dimensions] = self._league_design(
                        match.fixture
                    )
                    home_transform, away_transform = self._team_transforms(match.fixture)
                    design[2 * row : 2 * row + 2, self._team_slice(match.fixture.home_team_id)] = (
                        home_transform
                    )
                    design[2 * row : 2 * row + 2, self._team_slice(match.fixture.away_team_id)] = (
                        away_transform
                    )
                    self._augment_design(design[2 * row : 2 * row + 2], match)
                    goals.extend([match.home_goals, match.away_goals])
                    for team in (match.fixture.home_team_id, match.fixture.away_team_id):
                        self.appearances[team, match.fixture.season_id] += 1
                self._update(design, np.array(goals))
                self.updates += 1
            self._advance(as_of)
        except (ValueError, RuntimeError, np.linalg.LinAlgError):
            self._reset()
            raise
        self.as_of, self.competition_id, self._history = as_of, self.primary_competition, ordered
        self.fit_diagnostics = {
            "inference": "daily joint Laplace Gaussian filter",
            "updates": self.updates,
            "state_dimensions": len(self.mean),
            "training_matches": len(ordered),
            "posterior": "Gaussian conditional on fixed dynamics and empirical Bayes bridge",
        }
        return self

    def _prepare_observations(self, games):
        pass

    def _augment_design(self, design, match):
        pass

    def observation_design(self, population_design):
        """Population design expressed in this filter's own state coordinates."""
        return population_design

    def _team_transforms(self, fixture=None):
        """Club loadings on the home and away log rates, optionally per fixture."""
        return np.array([[1, 0], [0, -1]]), np.array([[0, -1], [1, 0]])

    def _update(self, design, goals):
        self.mean, self.covariance = poisson_laplace_update(
            self.mean, self.covariance, design, goals
        )

    @property
    def intercept(self):
        return self.mean[0]

    @property
    def home_advantage(self):
        return self.mean[1]

    @property
    def attack(self):
        return self.mean[self.league_dimensions :: 2]

    @property
    def defense(self):
        return self.mean[self.league_dimensions + 1 :: 2]

    def _uses_fitted_state(self, team: str, season: str) -> bool:
        """Only a club the boundary bridge recognizes gives up its fitted state."""
        if team not in self.team_index or self._last_season[team] == season:
            return team in self.team_index
        return not self._entry_replaces_state(team, season, self.as_of)

    def team_state(self, team: str, season: str) -> TeamPrior:
        if self.as_of is None:
            raise ValueError("Fit the model before prediction")
        if self._uses_fitted_state(team, season):
            block = self._team_slice(team)
            return TeamPrior(
                self.mean[block].copy(),
                self.covariance[block, block].copy(),
                self.entry_priors[team, season].source
                if (team, season) in self.entry_priors
                else "previous league state",
            )
        return self._entry_prior(team, season, self.as_of)

    def team_summary(self, team: str, season: str) -> dict:
        state = self.team_state(team, season)
        prior = self.entry_priors.get((team, season), state)
        return {
            "team_id": team,
            "attack_log_rate": float(state.mean[0]),
            "defense_log_rate": float(state.mean[1]),
            "attack_sd": float(np.sqrt(state.covariance[0, 0])),
            "defense_sd": float(np.sqrt(state.covariance[1, 1])),
            "attack_defense_covariance": float(state.covariance[0, 1]),
            "state_source": state.source,
            "season_matches": self.appearances[team, season],
            "entry_attack": float(prior.mean[0]),
            "entry_defense": float(prior.mean[1]),
            "entry_attack_sd": float(np.sqrt(prior.covariance[0, 0])),
            "entry_defense_sd": float(np.sqrt(prior.covariance[1, 1])),
        }

    def forecast_moments(self, fixture: Fixture) -> tuple[np.ndarray, np.ndarray]:
        self.validate_fixture(fixture)
        design = np.zeros((2, len(self.mean)))
        design[:, : self.league_dimensions] = self._league_design(fixture)
        extra_mean, extra_covariance = np.zeros(2), np.zeros((2, 2))
        for team, transform in zip(
            (fixture.home_team_id, fixture.away_team_id),
            self._team_transforms(fixture),
            strict=True,
        ):
            if self._uses_fitted_state(team, fixture.season_id):
                design[:, self._team_slice(team)] = transform
            else:
                prior = self.team_state(team, fixture.season_id)
                extra_mean += transform @ prior.mean
                extra_covariance += transform @ prior.covariance @ transform.T
        return (
            design @ self.mean + extra_mean,
            design @ self.covariance @ design.T + extra_covariance,
        )

    def predict_match(self, fixture: Fixture) -> Forecast:
        distribution = PoissonMixture(*self.forecast_moments(fixture), self.quadrature_order)
        return Forecast(distribution.outcome_probabilities(), distribution)

    def sample_forecast_state(self, rng: np.random.Generator, size: int = 1):
        if self.as_of is None:
            raise ValueError("Fit the model before sampling states")
        if type(size) is not int or size < 1:
            raise ValueError("State sample size must be a positive integer")
        snapshot = copy(self)
        snapshot.team_index = self.team_index.copy()
        snapshot._last_season = self._last_season.copy()
        snapshot.entry_priors = self.entry_priors.copy()
        snapshot.mean, snapshot.covariance = self.mean.copy(), self.covariance.copy()
        return SampledTeamStates(snapshot, rng, size)


class SampledTeamStates:
    def __init__(self, model: DynamicAttackDefense, rng: np.random.Generator, size: int):
        self.model, self.size, self.as_of = model, size, model.as_of
        root = np.linalg.cholesky(model.covariance)
        self.values = model.mean + rng.standard_normal((size, len(model.mean))) @ root.T
        self._entry_draws = {}
        self._rng = rng

    def _team(self, team: str, season: str) -> np.ndarray:
        if self.model._uses_fitted_state(team, season):
            return self.values[:, self.model._team_slice(team)]
        key = team, season
        if key not in self._entry_draws:
            prior = self.model.team_state(team, season)
            self._entry_draws[key] = (
                prior.mean
                + self._rng.standard_normal((self.size, 2)) @ np.linalg.cholesky(prior.covariance).T
            )
        return self._entry_draws[key]

    def rates(self, fixture: Fixture) -> tuple[np.ndarray, np.ndarray]:
        self.model.validate_fixture(fixture)
        home = self._team(fixture.home_team_id, fixture.season_id)
        away = self._team(fixture.away_team_id, fixture.season_id)
        league = (
            self.values[:, : self.model.league_dimensions] @ self.model._league_design(fixture).T
        )
        return (
            np.exp(league[:, 0] + home[:, 0] - away[:, 1]),
            np.exp(league[:, 1] + away[:, 0] - home[:, 1]),
        )

    def sample_scores(self, fixture: Fixture, rng: np.random.Generator, paths=None):
        home, away = self.rates(fixture)
        if paths is not None:
            home, away = home[paths], away[paths]
        return rng.poisson(home), rng.poisson(away)

    def predict_match(self, fixture: Fixture) -> Forecast:
        if self.size != 1:
            raise ValueError("Use sample_scores for a batch of forecast states")
        home, away = self.rates(fixture)
        scores = IndependentPoisson(float(home[0]), float(away[0]))
        return Forecast(scores.outcome_probabilities(), scores)
