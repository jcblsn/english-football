import copy

import numpy as np
from scipy.special import gammaln, logsumexp
from scipy.stats import binom, nbinom

from epl_forecast.models.poisson import PoissonMixture


def joint_logpmf(home, away, home_rate, away_rate, dispersion):
    total = home + away
    return (
        gammaln(dispersion + total)
        - gammaln(dispersion)
        - gammaln(home + 1)
        - gammaln(away + 1)
        + home * np.log(home_rate)
        + away * np.log(away_rate)
        - total * np.log(dispersion + home_rate + away_rate)
        - dispersion * np.log1p((home_rate + away_rate) / dispersion)
    )


class GammaPoissonMixture(PoissonMixture):
    """Gaussian state uncertainty plus an independent shared Gamma tempo per match."""

    def __init__(self, log_mean, log_covariance, order=9, dispersion=20.0):
        super().__init__(log_mean, log_covariance, order)
        if not np.isfinite(dispersion) or dispersion <= 0:
            raise ValueError("dispersion must be finite and positive")
        self.dispersion = dispersion

    def outcome_probabilities(self):
        total_rate = self.home_rates + self.away_rates
        p = self.dispersion / (self.dispersion + total_rate)
        share = self.home_rates / total_rate
        # Given total goals, the home share is Binomial, including the zero-total draw.
        limit = int(np.max(nbinom.ppf(1 - 1e-12, self.dispersion, p)))
        result = np.zeros(3)
        for start in range(0, limit + 1, 256):
            total = np.arange(start, min(limit + 1, start + 256))[:, None]
            mass = nbinom.pmf(total, self.dispersion, p) * self.weights
            result[0] += np.sum(mass * binom.sf(total // 2, total, share))
            result[1] += np.sum(mass * (total % 2 == 0) * binom.pmf(total // 2, total, share))
            result[2] += np.sum(mass * binom.cdf((total - 1) // 2, total, share))
        return tuple(result / result.sum())

    def log_probability(self, home_goals, away_goals):
        return float(
            logsumexp(
                np.log(self.weights)
                + joint_logpmf(
                    home_goals, away_goals, self.home_rates, self.away_rates, self.dispersion
                )
            )
        )

    def grid(self, max_goals=10):
        if type(max_goals) is not int or max_goals < 0:
            raise ValueError("max_goals must be a nonnegative integer")
        goals = np.arange(max_goals + 1)
        grid = (
            np.exp(
                joint_logpmf(
                    goals[:, None, None],
                    goals[None, :, None],
                    self.home_rates,
                    self.away_rates,
                    self.dispersion,
                )
            )
            @ self.weights
        )
        return grid, max(0.0, 1.0 - float(grid.sum()))

    def sample(self, rng, size):
        component = rng.choice(len(self.weights), size=size, p=self.weights)
        tempo = rng.gamma(self.dispersion, 1 / self.dispersion, size)
        return (
            rng.poisson(tempo * self.home_rates[component]),
            rng.poisson(tempo * self.away_rates[component]),
        )


class ScoreMixture:
    def __init__(self, components, weights):
        flattened, masses = [], []
        for component, weight in zip(components, weights, strict=True):
            if isinstance(component, ScoreMixture):
                flattened.extend(component.components)
                masses.extend(weight * component.weights)
            else:
                flattened.append(component)
                masses.append(weight)
        components, weights = flattened, masses
        self.components, self.weights = components, np.asarray(weights)
        self.home_rate = float(self.weights @ [c.home_rate for c in components])
        self.away_rate = float(self.weights @ [c.away_rate for c in components])
        means = np.array([c.log_mean for c in components])
        self.log_mean = self.weights @ means
        deviations = means - self.log_mean
        self.log_covariance = (
            np.einsum("i,ijk->jk", self.weights, [c.log_covariance for c in components])
            + (deviations.T * self.weights) @ deviations
        )

    def uncertainty_components(self):
        mean = np.array([self.home_rate, self.away_rate])
        second = np.zeros((2, 2))
        tempo = np.zeros((2, 2))
        for weight, component in zip(self.weights, self.components, strict=True):
            rates = np.column_stack([component.home_rates, component.away_rates])
            moment = (rates.T * component.weights) @ rates
            second += weight * moment
            if hasattr(component, "dispersion"):
                tempo += weight * moment / component.dispersion
            if hasattr(component, "process_scale"):
                tempo += weight * np.diag(
                    2
                    * component.process_scale
                    * np.array([component.home_rate, component.away_rate])
                )
        state = second - np.outer(mean, mean)
        return {
            "state_rate_covariance": state.tolist(),
            "match_tempo_covariance": tempo.tolist(),
            "poisson_variance": mean.tolist(),
            "total_score_covariance": (state + tempo + np.diag(mean)).tolist(),
            "axis_order": ["home", "away"],
        }

    def outcome_probabilities(self):
        return tuple(self.weights @ [c.outcome_probabilities() for c in self.components])

    def log_probability(self, home_goals, away_goals):
        log_weights = np.full(len(self.weights), -np.inf)
        np.log(self.weights, out=log_weights, where=self.weights > 0)
        return float(
            logsumexp(
                log_weights + [c.log_probability(home_goals, away_goals) for c in self.components]
            )
        )

    def grid(self, max_goals=10):
        grids = [c.grid(max_goals) for c in self.components]
        grid = np.einsum("i,ijk->jk", self.weights, [g for g, _ in grids])
        return grid, max(0.0, 1.0 - float(grid.sum()))

    def sample(self, rng, size):
        indices = rng.choice(len(self.weights), size=size, p=self.weights)
        home, away = np.empty(size, dtype=int), np.empty(size, dtype=int)
        for index, component in enumerate(self.components):
            mask = indices == index
            home[mask], away[mask] = component.sample(rng, int(mask.sum()))
        return home, away


def shift_scores(scores, shift):
    """A copy of a score distribution with +shift on the home and −shift on the away log rate.

    The operation is generic: it moves the rates of one match. It knows nothing about why
    the caller wants them moved, so the simulator does not depend on a product-specific
    module to use it.
    """
    if isinstance(scores, ScoreMixture):
        return ScoreMixture([shift_scores(c, shift) for c in scores.components], scores.weights)
    shifted = copy.copy(scores)
    shifted.log_mean = scores.log_mean + np.array([shift, -shift])
    shifted.home_rates = scores.home_rates * np.exp(shift)
    shifted.away_rates = scores.away_rates * np.exp(-shift)
    shifted.home_rate = float(shifted.weights @ shifted.home_rates)
    shifted.away_rate = float(shifted.weights @ shifted.away_rates)
    return shifted


def score_diagnostics(scores):
    from scipy.stats import poisson

    if isinstance(scores, ScoreMixture):
        rows = [score_diagnostics(c) for c in scores.components]
        return {key: float(scores.weights @ [row[key] for row in rows]) for key in rows[0]}
    if hasattr(scores, "diagnostics"):
        return scores.diagnostics()
    home = np.atleast_1d(getattr(scores, "home_rates", scores.home_rate))
    away = np.atleast_1d(getattr(scores, "away_rates", scores.away_rate))
    weights = getattr(scores, "weights", np.ones(1))
    if isinstance(scores, GammaPoissonMixture):
        k = scores.dispersion
        total_tail = nbinom.sf(5, k, k / (k + home + away))
        home_zero, away_zero = (k / (k + home)) ** k, (k / (k + away)) ** k
        both_zero = (k / (k + home + away)) ** k
    else:
        total_tail = poisson.sf(5, home + away)
        home_zero, away_zero = np.exp(-home), np.exp(-away)
        both_zero = home_zero * away_zero
    return {
        "p_total_goals_ge6": float(weights @ total_tail),
        "p_scoreless": float(weights @ both_zero),
        "p_both_score": float(weights @ (1 - home_zero - away_zero + both_zero)),
        "expected_home_goals": float(scores.home_rate),
        "expected_away_goals": float(scores.away_rate),
    }
