"""Joint goals/xG likelihood from a thinned Poisson opportunity process."""

from datetime import date

import numpy as np
from scipy.special import gammaln, logsumexp

from epl_forecast.models.gaussian import LikelihoodDomainError

DEFAULT_PROVIDER = "understat"


def chance_rows(observations):
    """Validate provider xG rows and index them by match for daily filtering."""
    rows = {}
    for row in observations:
        key = row["match_id"]
        if key in rows:
            raise ValueError("Duplicate xG match observation")
        day, available = (
            date.fromisoformat(row["match_date"]),
            date.fromisoformat(row["available_on"]),
        )
        if available <= day:
            raise ValueError("xG cannot be available before the next calendar day")
        xg = (float(row["home_xg"]), float(row["away_xg"]))
        if not np.isfinite(xg).all() or min(xg) < 0:
            raise ValueError("Observed xG must be finite and nonnegative")
        rows[key] = (
            day,
            available,
            int(row["home_goals"]),
            int(row["away_goals"]),
            *xg,
            row.get("provider", DEFAULT_PROVIDER),
        )
    return rows


class ChanceObservation:
    """Opportunities N ~ Poisson(rate / p), goals G ~ Binomial(N, p), xG X ~ Gamma(N, s p).

    The provider scale s gives E[X | rate] = s rate. The M7 Understat channel is s = 1.
    """

    def __init__(self, goals, xg, chance_probability, provider_scale=1.0):
        self.goals, self.xg = np.asarray(goals), np.asarray(xg, dtype=float)
        p = chance_probability
        if not np.isfinite(p) or not 0 < p < 1:
            raise ValueError("Chance probability must be in (0, 1)")
        if self.goals.ndim != 1 or self.xg.shape != self.goals.shape:
            raise ValueError("Goals and xG must be matching vectors")
        scale = np.asarray(provider_scale, dtype=float)
        if not np.isfinite(scale).all() or np.any(scale <= 0):
            raise ValueError("Provider scale must be finite and positive")
        if (
            not np.isfinite(self.goals).all()
            or np.any(self.goals < 0)
            or np.any(self.goals != np.floor(self.goals))
        ):
            raise ValueError("Goals must be nonnegative integers")
        if np.any(np.isinf(self.xg)) or np.any(self.xg < 0):
            raise ValueError("xG must be nonnegative and finite, or NaN for missing")
        if np.any((self.xg == 0) & (self.goals > 0)):
            raise ValueError("Positive goals with zero xG are outside the opportunity model")
        self.p, self._scale = p, scale
        self.scale = np.broadcast_to(scale, self.xg.shape)
        self.terms = [
            self._terms(g, x, s, 128) if x > 0 else None
            for g, x, s in zip(self.goals, self.xg, self.scale, strict=True)
        ]

    def _terms(self, goals, xg, scale, count):
        missed = np.arange(0 if goals else 1, count, dtype=float)
        total = goals + missed
        constant = (
            -gammaln(goals + 1)
            - gammaln(missed + 1)
            - gammaln(total)
            + missed * np.log((1 - self.p) / self.p)
            + (total - 1) * np.log(xg)
            - total * np.log(self.p * scale)
            - xg / (self.p * scale)
        )
        return missed, total, constant

    def __call__(self, eta):
        rates = np.exp(eta)
        if not np.isfinite(rates).all():
            return -np.inf, np.zeros(len(eta)), np.eye(len(eta))
        logp, score, curvature = 0.0, np.empty(len(eta)), np.empty(len(eta))
        for i, (g, x, s, rate) in enumerate(
            zip(self.goals, self.xg, self.scale, rates, strict=True)
        ):
            if np.isnan(x):
                logp += g * eta[i] - rate - gammaln(g + 1)
                score[i], curvature[i] = g - rate, rate
            elif x == 0:
                logp -= rate / self.p
                score[i], curvature[i] = -rate / self.p, rate / self.p
            else:
                terms = self.terms[i]
                while True:
                    missed, total, constant = terms
                    values = total * eta[i] + constant
                    normalizer = logsumexp(values)
                    weights = np.exp(values - normalizer)
                    ratio = (
                        rate * (1 - self.p) * x / (s * self.p**2) / ((missed[-1] + 1) * total[-1])
                    )
                    if ratio < 1 and weights[-1] * ratio / (1 - ratio) < 1e-14:
                        break
                    if len(missed) >= 8191:
                        raise LikelihoodDomainError(
                            "Opportunity likelihood series failed to converge"
                        )
                    terms = self._terms(g, x, s, 2 * (int(missed[-1]) + 1))
                expected = weights @ missed
                variance = weights @ (missed - expected) ** 2
                logp += normalizer - rate / self.p
                score[i], curvature[i] = g + expected - rate / self.p, rate / self.p - variance
        return float(logp), score, np.diag(curvature)

    def sample(self, log_rates, rng):
        opportunities = rng.poisson(np.exp(log_rates) / self.p)
        goals = rng.binomial(opportunities, self.p)
        xg = rng.gamma(opportunities, self.p * np.broadcast_to(self._scale, opportunities.shape))
        return goals, xg
