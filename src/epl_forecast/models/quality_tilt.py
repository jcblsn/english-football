from copy import copy, deepcopy
from itertools import product

import numpy as np
from scipy.special import logsumexp

from epl_forecast.models.base import Forecast, selected_mask
from epl_forecast.models.dynamic import DynamicAttackDefense
from epl_forecast.models.gaussian import score_laplace_update
from epl_forecast.models.poisson import PoissonMixture
from epl_forecast.models.promotion import TeamPrior
from epl_forecast.models.quality_tilt_scores import GammaPoissonMixture, ScoreMixture

QT_FROM_AD = np.array([[0.5, 0.5], [0.5, -0.5]])
AD_FROM_QT = np.array([[1, 1], [1, -1]])


class QualityTiltFilter(DynamicAttackDefense):
    def __init__(
        self,
        quality_retention=0.9,
        quality_sd=0.12,
        tilt_retention=0.65,
        tilt_sd=0.10,
        annual_league_sd=0.04,
        annual_home_sd=0.025,
        initial_team_sd=0.4,
        dispersion=20.0,
        quadrature_order=9,
        independent_poisson=False,
    ):
        if independent_poisson:
            dispersion = None
        for retention in (quality_retention, tilt_retention):
            if not np.isfinite(retention) or not 0 < retention <= 1:
                raise ValueError("Retention must be in (0, 1]")
        for sd in (quality_sd, tilt_sd, annual_home_sd):
            if not np.isfinite(sd) or sd <= 0:
                raise ValueError("State standard deviations must be positive")
        if dispersion is not None and (not np.isfinite(dispersion) or dispersion <= 0):
            raise ValueError("dispersion must be positive or None for independent Poisson")
        self.quality_retention, self.tilt_retention = quality_retention, tilt_retention
        self.quality_sd, self.tilt_sd = quality_sd, tilt_sd
        self.annual_home_sd, self.dispersion = annual_home_sd, dispersion
        super().__init__(
            annual_league_sd=annual_league_sd,
            initial_team_sd=initial_team_sd,
            quadrature_order=quadrature_order,
            promotion_performance=False,
        )

    def _reset(self):
        super()._reset()
        self.log_evidence = 0.0

    def _entry_prior(self, team, season, as_of):
        prior = super()._entry_prior(team, season, as_of)
        return TeamPrior(
            QT_FROM_AD @ prior.mean, QT_FROM_AD @ prior.covariance @ QT_FROM_AD.T, prior.source
        )

    def _team_transforms(self, fixture=None):
        return np.array([[1, 1], [-1, 1]]), np.array([[-1, 1], [1, 1]])

    def transition(self, years, dimensions):
        if years < 0:
            raise ValueError("Cannot evolve a state backwards")
        rho = np.array([self.quality_retention, self.tilt_retention])
        sd = np.array([self.quality_sd, self.tilt_sd])
        factor = rho**years
        variance = sd**2 * np.array(
            [years if r == 1 else (1 - f**2) / (1 - r**2) for r, f in zip(rho, factor, strict=True)]
        )
        leading = self.league_dimensions
        return (
            np.r_[np.ones(leading), np.tile(factor, (dimensions - leading) // 2)],
            np.r_[
                self.league_innovation_sd() ** 2 * years,
                np.tile(variance, (dimensions - leading) // 2),
            ],
        )

    def league_innovation_sd(self):
        """Annual random-walk scale for each slot of the leading league block."""
        return np.array([self.annual_league_sd, self.annual_home_sd])

    def team_transition(self, years):
        """Decay and innovation variance for one club's two state slots.

        This deliberately uses the club dynamics rather than any subclass
        augmentation of the state vector.
        """
        leading = self.league_dimensions
        decay, variance = QualityTiltFilter.transition(self, years, leading + 2)
        return decay[leading:], variance[leading:]

    def _advance(self, day):
        if self._state_date is not None:
            decay, variance = self.transition(
                (day - self._state_date).days / 365.25, len(self.mean)
            )
            self.mean *= decay
            self.covariance = self.covariance * np.outer(decay, decay) + np.diag(variance)
        self._state_date = day

    def _update(self, design, goals):
        self.mean, self.covariance, evidence = score_laplace_update(
            self.mean, self.covariance, design, goals, self.dispersion
        )
        self.log_evidence += evidence

    @property
    def attack(self):
        return self.mean[self.league_dimensions :: 2] + self.mean[self.league_dimensions + 1 :: 2]

    @property
    def defense(self):
        return self.mean[self.league_dimensions :: 2] - self.mean[self.league_dimensions + 1 :: 2]

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
        return DynamicAttackDefense.forecast_moments(snapshot, fixture)

    def score_distribution(self, fixture):
        moments = self.forecast_moments(fixture)
        if self.dispersion is None:
            return PoissonMixture(*moments, self.quadrature_order)
        return GammaPoissonMixture(*moments, self.quadrature_order, self.dispersion)

    def predict_match(self, fixture):
        scores = self.score_distribution(fixture)
        return Forecast(scores.outcome_probabilities(), scores)

    def sample_forecast_state(self, rng, size=1):
        return ForwardQualityTiltStates(self, rng, size)

    def sample_goal_rates(self, home_rate, away_rate, rng):
        tempo = (
            1.0
            if self.dispersion is None
            else rng.gamma(self.dispersion, 1 / self.dispersion, len(home_rate))
        )
        return rng.poisson(tempo * home_rate), rng.poisson(tempo * away_rate)

    def team_summary(self, team, season):
        state = self.team_state(team, season)
        return state_summary(team, state)


def state_summary(team, state):
    ad_mean = AD_FROM_QT @ state.mean
    ad_covariance = AD_FROM_QT @ state.covariance @ AD_FROM_QT.T
    return {
        "team_id": team,
        "quality": float(state.mean[0]),
        "tilt": float(state.mean[1]),
        "quality_sd": float(np.sqrt(state.covariance[0, 0])),
        "tilt_sd": float(np.sqrt(state.covariance[1, 1])),
        "quality_tilt_covariance": float(state.covariance[0, 1]),
        "attack_log_rate": float(ad_mean[0]),
        "defense_log_rate": float(ad_mean[1]),
        "attack_sd": float(np.sqrt(ad_covariance[0, 0])),
        "defense_sd": float(np.sqrt(ad_covariance[1, 1])),
        "state_source": state.source,
    }


class BayesianQualityTilt:
    def __init__(
        self, specifications=None, prior_weights=None, quadrature_order=9, independent_poisson=False
    ):
        self.specifications = (
            specifications
            if specifications is not None
            else [
                dict(
                    quality_retention=rq, quality_sd=sq, tilt_retention=rt, tilt_sd=st, dispersion=k
                )
                for (rq, sq), (rt, st), k in product(
                    [(0.85, 0.09), (0.97, 0.16)], [(0.5, 0.07), (0.85, 0.14)], [8.0, 30.0, 100.0]
                )
            ]
        )
        if not self.specifications:
            raise ValueError("At least one dynamics specification is required")
        if independent_poisson and specifications is None:
            self.specifications = self.specifications[::3]
        self.members = [
            QualityTiltFilter(
                **{**spec, **({"dispersion": None} if independent_poisson else {})},
                quadrature_order=quadrature_order,
            )
            for spec in self.specifications
        ]
        weights = np.ones(len(self.members)) if prior_weights is None else np.asarray(prior_weights)
        if (
            weights.shape != (len(self.members),)
            or not np.all(np.isfinite(weights))
            or np.any(weights <= 0)
        ):
            raise ValueError("Prior weights must be finite and positive, one per specification")
        self.prior_weights = weights / weights.sum()
        self.weights = self.prior_weights.copy()
        self.as_of = None

    def fit(self, matches, as_of):
        try:
            for member in self.members:
                member.fit(matches, as_of)
        except (ValueError, RuntimeError, np.linalg.LinAlgError):
            self.as_of = None
            for member in self.members:
                member._reset()
            raise
        log_weights = np.log(self.prior_weights) + [m.log_evidence for m in self.members]
        self.weights = np.exp(log_weights - logsumexp(log_weights))
        self.as_of = as_of
        self.team_index = self.members[0].team_index
        self.fit_diagnostics = {
            "inference": "daily joint Laplace filters with approximate Bayesian model weights",
            "weight_evidence": "chronological joint daily predictive likelihood (Laplace)",
            "effective_specifications": float(1 / (self.weights @ self.weights)),
            "future_states": "calendar-time Quality/Tilt and league/home transitions",
            "promotion": "frozen M4 promoted-population prior transformed to Quality/Tilt",
            "specifications": [
                {
                    **spec,
                    "dispersion": member.dispersion,
                    "prior_weight": float(prior),
                    "posterior_weight": float(weight),
                    "log_evidence": member.log_evidence,
                }
                for spec, member, prior, weight in zip(
                    self.specifications, self.members, self.prior_weights, self.weights, strict=True
                )
            ],
        }
        return self

    @property
    def intercept(self):
        return float(self.weights @ [m.intercept for m in self.members])

    @property
    def home_advantage(self):
        return float(self.weights @ [m.home_advantage for m in self.members])

    def team_summary(self, team, season):
        states = [m.team_state(team, season) for m in self.members]
        means = np.array([s.mean for s in states])
        mean = self.weights @ means
        deviations = means - mean
        covariance = np.einsum("i,ijk->jk", self.weights, [s.covariance for s in states])
        covariance += (deviations.T * self.weights) @ deviations
        summary = state_summary(team, TeamPrior(mean, covariance, states[0].source))
        summary["season_matches"] = self.members[0].appearances[team, season]
        return summary

    def predict_match(self, fixture):
        scores = ScoreMixture([m.score_distribution(fixture) for m in self.members], self.weights)
        return Forecast(scores.outcome_probabilities(), scores)

    def sample_forecast_state(self, rng, size=1):
        return ForwardQualityTiltStates(self, rng, size)


class ForwardQualityTiltStates:
    evolves_future_states = True

    def __init__(self, model, rng, size):
        if model.as_of is None:
            raise ValueError("Fit the model before sampling states")
        if type(size) is not int or size < 1:
            raise ValueError("State sample size must be a positive integer")
        self.as_of, self.size, self.rng = model.as_of, size, rng
        members = getattr(model, "members", [model])
        weights = getattr(model, "weights", np.ones(1))
        indices = rng.choice(len(members), size=size, p=weights)
        self.groups = []
        for index, member in enumerate(members):
            positions = np.flatnonzero(indices == index)
            if not len(positions):
                continue
            snapshot = deepcopy(member)
            values = member.mean + rng.standard_normal((len(positions), len(member.mean))) @ (
                np.linalg.cholesky(member.covariance).T
            )
            self.groups.append([positions, snapshot, values, self.as_of, {}])

    def sample_scores(self, fixture, rng, paths=None, log_rate_shift=0.0):
        home, away = np.empty(self.size, dtype=int), np.empty(self.size, dtype=int)
        wanted = selected_mask(self.size, paths)
        for group in self.groups:
            positions, model = group[0], group[1]
            # Every group advances to the fixture date even when no selected path needs it.
            home_rate, away_rate = self._group_rates(group, fixture, rng)
            keep = slice(None) if wanted is None else wanted[positions]
            target = positions if wanted is None else positions[keep]
            home[target], away[target] = model.sample_goal_rates(
                home_rate[keep] * np.exp(log_rate_shift),
                away_rate[keep] * np.exp(-log_rate_shift),
                rng,
            )
        return (home, away) if paths is None else (home[paths], away[paths])

    def rates(self, fixture, rng=None):
        """Latent rates for this fixture, advancing the forward state as usual."""
        home, away = np.empty(self.size), np.empty(self.size)
        for group in self.groups:
            home[group[0]], away[group[0]] = self._group_rates(group, fixture, rng)
        return home, away

    def _group_rates(self, group, fixture, rng):
        """Advance one specification group to the fixture and return its latent rates."""
        positions, model, values, day, entries = group
        model.validate_fixture(fixture)
        if fixture.match_date < day:
            raise ValueError("Forward simulation requires chronological fixtures")
        # New-season entrants are drawn at the forecast cutoff, then evolved to kickoff.
        for team in (fixture.home_team_id, fixture.away_team_id):
            if not model._uses_fitted_state(team, fixture.season_id):
                key = team, fixture.season_id
                if key not in entries:
                    prior = model.team_state(team, fixture.season_id)
                    decay, variance = model.team_transition((day - self.as_of).days / 365.25)
                    entry_mean = prior.mean * decay
                    entry_cov = prior.covariance * np.outer(decay, decay) + np.diag(variance)
                    entries[key] = entry_mean + self.rng.standard_normal((len(positions), 2)) @ (
                        np.linalg.cholesky(entry_cov).T
                    )
        years = (fixture.match_date - day).days / 365.25
        if years:
            decay, variance = model.transition(years, values.shape[1])
            values *= decay
            values += self.rng.standard_normal(values.shape) * np.sqrt(variance)
            decay, variance = model.team_transition(years)
            for entry in entries.values():
                entry *= decay
                entry += self.rng.standard_normal(entry.shape) * np.sqrt(variance)
        group[3] = fixture.match_date

        def team_value(team):
            key = team, fixture.season_id
            if key in entries:
                return entries[key]
            index = model.league_dimensions + 2 * model.team_index[team]
            return values[:, index : index + 2]

        home, away = team_value(fixture.home_team_id), team_value(fixture.away_team_id)
        quality, tilt = home[:, 0] - away[:, 0], home[:, 1] + away[:, 1]
        # Every leading league slot must reach the simulated rate, not only the first two.
        league = values[:, : model.league_dimensions] @ model._league_design(fixture).T
        return np.exp(league[:, 0] + quality + tilt), np.exp(league[:, 1] - quality + tilt)
