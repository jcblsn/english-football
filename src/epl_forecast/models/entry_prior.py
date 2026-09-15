"""Transition-aware entry priors for a club arriving from another division.

A continuing club keeps the target-division state the filter already holds for
it. A club entering the division is described instead by a prior learned from
earlier entrants of the same transition, optionally conditioned on the strength
it showed in its source division and on a time-weighted memory of its own older
target-division form. Nothing here reads a provider: every feature is a summary
of league seasons the archive already holds.
"""

from dataclasses import dataclass
from datetime import date
from functools import lru_cache

import numpy as np
from numpy.polynomial.legendre import leggauss

from epl_forecast.competitions import COMPETITION_IDS, ENTRY_SOURCE_COMPETITION_IDS
from epl_forecast.models.promotion import (
    TeamPrior,
    entry_label,
    preceding_season,
    season_strengths,
)

LEVELS = ("population", "transition", "source", "memory")
LABELS = ("season", "entry")
DIMENSIONS = ("attack", "defense")
OUTSIDE = "outside"
MEMORY_TIMESCALES = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0, np.inf)
FRESHEST_GAP = 2
MINIMUM_COHORT = 6
DIVISIONS = ENTRY_SOURCE_COMPETITION_IDS


def transition_id(source_competition: str | None, target_competition: str) -> str:
    return f"{source_competition or OUTSIDE}->{target_competition}"


def memory_weight(age: float, timescale: float) -> float:
    """How much of an old target-division season still counts after `age` years."""
    if age < FRESHEST_GAP:
        raise ValueError("An entering club last played the division at least two years earlier")
    return 1.0 if np.isinf(timescale) else float(np.exp(-(age - FRESHEST_GAP) / timescale))


def _season_year(season: str) -> int:
    return int(season[:4])


def club_features(seasons, competition: str, season: str, team: str) -> dict | None:
    """Everything known about an entering club before its first target-division match.

    Returns None for a continuing club, and for a club whose status cannot be
    read because the preceding target season is not in the archive.
    """
    previous = preceding_season(season)
    if (competition, previous) not in seasons:
        return None
    target_history = season_strengths(seasons[competition, previous])
    if team in target_history.teams:
        return None
    source_competition = next(
        (
            other
            for other in DIVISIONS
            if other != competition
            and (other, previous) in seasons
            and team in season_strengths(seasons[other, previous]).teams
        ),
        None,
    )
    row = {
        "competition_id": competition,
        "season_id": season,
        "team_id": team,
        "transition": transition_id(source_competition, competition),
        "source_competition": source_competition,
        "source_season": previous if source_competition else None,
    }
    available = [target_history.available_on]
    for prefix, key in (("source", source_competition), ("memory", None)):
        if prefix == "source":
            strengths = season_strengths(seasons[key, previous]) if key else None
        else:
            older = [
                s
                for (c, s) in seasons
                if c == competition and s < season and team in season_strengths(seasons[c, s]).teams
            ]
            strengths = season_strengths(seasons[competition, max(older)]) if older else None
            row["memory_season"] = max(older) if older else None
            row["memory_age"] = (
                float(_season_year(season) - _season_year(max(older))) if older else None
            )
        for i, dimension in enumerate(DIMENSIONS):
            prior = strengths.teams[team] if strengths else None
            row[f"{prefix}_{dimension}"] = float(prior.mean[i]) if prior else None
            row[f"{prefix}_{dimension}_variance"] = float(prior.covariance[i, i]) if prior else None
        if strengths:
            available.append(strengths.available_on)
    row["features_available_on"] = str(max(available))
    return row


@lru_cache(maxsize=8)
def entry_panel(seasons_items: tuple, competition: str, first: int = 10) -> tuple[dict, ...]:
    """Every labeled entrant into one division: its features beside its realized entry."""
    seasons = dict(seasons_items)
    rows = []
    for (target_competition, season), matches in sorted(seasons.items()):
        if target_competition != competition:
            continue
        strengths = season_strengths(matches)
        for team in sorted(strengths.teams):
            features = club_features(seasons, competition, season, team)
            if features is None:
                continue
            label = entry_label(strengths, matches, team, first)
            summary = strengths.teams[team]
            rows.append(
                {
                    **features,
                    **{k: v for k, v in label.items() if k not in ("team_id", "season_id")},
                    **{
                        f"season_{dimension}{suffix}": float(value)
                        for i, dimension in enumerate(DIMENSIONS)
                        for suffix, value in (
                            ("", summary.mean[i]),
                            ("_variance", summary.covariance[i, i]),
                        )
                    },
                    "available_on": str(
                        max(
                            date.fromisoformat(features["features_available_on"]),
                            strengths.available_on,
                        )
                    ),
                }
            )
    return tuple(rows)


@dataclass(frozen=True)
class EntryRegression:
    features: tuple[str, ...]
    coefficients: np.ndarray
    covariance: np.ndarray
    residual_variance: float
    residual_sd_interval: tuple[float, float]
    log_evidence: float
    standardized_residuals: np.ndarray
    cohorts: int


def _marginal_regression(x, xv, y, yv, prior_sd, nodes=33, scale_prior=0.3, largest_scale=1.5):
    """Errors-in-variables Gaussian regression, marginalizing the residual scale.

    Coefficient priors are deliberately tight and the residual scale is
    integrated rather than plugged in, so a small cohort produces a wide entry
    prior instead of a confident one.
    """
    beta_prior = np.diag(np.asarray(prior_sd, dtype=float) ** 2)
    beta_precision = np.linalg.inv(beta_prior)
    beta_logdet = float(np.linalg.slogdet(beta_prior)[1])
    quadrature_nodes, quadrature_weights = leggauss(nodes)
    scales = (quadrature_nodes + 1) * (largest_scale / 2)
    input_noise = np.zeros(len(y))
    for _ in range(3):
        log_weights, means, covariances = [], [], []
        for scale, weight in zip(scales, quadrature_weights, strict=True):
            variance = yv + input_noise + scale**2
            precision = beta_precision + (x.T / variance) @ x
            covariance = np.linalg.inv(precision)
            mean = covariance @ (x.T @ (y / variance))
            quadratic = float(y @ (y / variance) - mean @ precision @ mean)
            logdet = float(np.log(variance).sum() + beta_logdet + np.linalg.slogdet(precision)[1])
            log_weights.append(
                np.log(weight)
                - 0.5 * (quadratic + logdet + len(y) * np.log(2 * np.pi))
                - 0.5 * (scale / scale_prior) ** 2
            )
            means.append(mean)
            covariances.append(covariance)
        log_weights = np.array(log_weights)
        evidence = float(np.logaddexp.reduce(log_weights))
        probabilities = np.exp(log_weights - evidence)
        means = np.asarray(means)
        coefficients = probabilities @ means
        deviations = means - coefficients
        covariance = (
            np.einsum("i,ijk->jk", probabilities, covariances)
            + (deviations.T * probabilities) @ deviations
        )
        second_moment = np.outer(coefficients, coefficients) + covariance
        input_noise = np.einsum("nij,ij->n", xv, second_moment)
    residual_variance = float(probabilities @ scales**2)
    total = yv + input_noise + residual_variance
    return {
        "coefficients": coefficients,
        "covariance": covariance,
        "residual_variance": residual_variance,
        "residual_sd_interval": tuple(
            map(float, np.interp([0.05, 0.95], np.cumsum(probabilities), scales))
        ),
        "log_evidence": evidence,
        "standardized_residuals": (y - x @ coefficients) / np.sqrt(total),
    }


def _design(rows, dimension, features, timescale):
    x = [np.ones(len(rows))]
    variances = [np.zeros(len(rows))]
    for feature in features:
        if feature == "source":
            x.append(np.array([r[f"source_{dimension}"] for r in rows]))
            variances.append(np.array([r[f"source_{dimension}_variance"] for r in rows]))
        else:
            weights = np.array(
                [
                    0.0 if r["memory_age"] is None else memory_weight(r["memory_age"], timescale)
                    for r in rows
                ]
            )
            x.append(weights * np.array([r[f"memory_{dimension}"] or 0.0 for r in rows]))
            variances.append(
                weights**2 * np.array([r[f"memory_{dimension}_variance"] or 0.0 for r in rows])
            )
    design = np.column_stack(x)
    covariance = np.zeros((len(rows), len(x), len(x)))
    for i, variance in enumerate(variances):
        covariance[:, i, i] = variance
    return design, covariance


def _feature_row(row, dimension, features, timescale):
    values, variances = [1.0], [0.0]
    for feature in features:
        if feature == "source":
            values.append(row[f"source_{dimension}"])
            variances.append(row[f"source_{dimension}_variance"])
        else:
            weight = (
                0.0 if row["memory_age"] is None else memory_weight(row["memory_age"], timescale)
            )
            values.append(weight * (row[f"memory_{dimension}"] or 0.0))
            variances.append(weight**2 * (row[f"memory_{dimension}_variance"] or 0.0))
    return np.array(values), np.diag(variances)


class EntryPriorModel:
    """One entry rule for every boundary crosser into a single division.

    `population` ignores the transition entirely; `transition` learns its mean
    and spread; `source` adds the club's immediately preceding source-division
    season where that division is modeled; `memory` adds the club's own older
    target-division season, weighted by a decay timescale that is learned rather
    than assumed.
    """

    def __init__(
        self,
        seasons,
        competition: str,
        target_season: str,
        as_of: date,
        level: str = "memory",
        initial_team_sd: float = 0.4,
        first: int = 10,
        label: str = "season",
    ) -> None:
        if level not in LEVELS:
            raise ValueError(f"Unknown entry-prior level: {level}")
        if label not in LABELS:
            raise ValueError(f"Unknown entry-prior training label: {label}")
        if competition not in COMPETITION_IDS:
            raise ValueError(f"Entry priors cover the modeled divisions, not {competition}")
        self.seasons = dict(seasons)
        self.competition, self.target_season, self.as_of = competition, target_season, as_of
        self.level, self.initial_team_sd, self.first = level, initial_team_sd, first
        self.label = label
        self.rows = [
            row
            for row in entry_panel(tuple(sorted(self.seasons.items())), competition, first)
            if row["season_id"] < target_season and date.fromisoformat(row["available_on"]) <= as_of
        ]
        self.timescales = MEMORY_TIMESCALES if level == "memory" else (np.inf,)
        self._regressions, self._residual_correlation = {}, {}
        self._fit()

    def _transition_features(self, transition):
        rows = [r for r in self.rows if r["transition"] == transition]
        if self.level == "population" or len(rows) < MINIMUM_COHORT:
            return rows, None
        features = []
        if self.level in ("source", "memory") and all(r["source_attack"] is not None for r in rows):
            features.append("source")
        if self.level == "memory":
            features.append("memory")
        return rows, tuple(features)

    def _fit(self):
        self.transitions = sorted({r["transition"] for r in self.rows})
        log_evidence = np.zeros(len(self.timescales))
        for transition in self.transitions:
            rows, features = self._transition_features(transition)
            if features is None:
                continue
            prior_sd = [0.6] + [0.5] * len(features)
            for index, timescale in enumerate(self.timescales):
                for dimension in DIMENSIONS:
                    x, xv = _design(rows, dimension, features, timescale)
                    y = np.array([r[f"{self.label}_{dimension}"] for r in rows])
                    yv = np.array([r[f"{self.label}_{dimension}_variance"] for r in rows])
                    fitted = _marginal_regression(x, xv, y, yv, prior_sd)
                    self._regressions[transition, dimension, index] = EntryRegression(
                        features,
                        fitted["coefficients"],
                        fitted["covariance"],
                        fitted["residual_variance"],
                        fitted["residual_sd_interval"],
                        fitted["log_evidence"],
                        fitted["standardized_residuals"],
                        len(rows),
                    )
                    log_evidence[index] += fitted["log_evidence"]
        self.timescale_weights = np.exp(log_evidence - np.logaddexp.reduce(log_evidence))
        for transition in self.transitions:
            residuals = [
                self._regressions.get((transition, dimension, 0)) for dimension in DIMENSIONS
            ]
            if any(r is None for r in residuals):
                continue
            a, d = (r.standardized_residuals for r in residuals)
            # Shrink towards independence: a handful of entrants cannot resolve this correlation.
            correlation = float(np.corrcoef(a, d)[0, 1]) * len(a) / (len(a) + 12)
            self._residual_correlation[transition] = float(np.clip(correlation, -0.8, 0.8))

    def population_prior(self, label="target-league population"):
        return TeamPrior(np.zeros(2), np.eye(2) * self.initial_team_sd**2, label)

    def features(self, team: str) -> dict | None:
        return club_features(self.seasons, self.competition, self.target_season, team)

    def prior(self, team: str) -> TeamPrior | None:
        """The entry prior for a boundary crosser, or None for a continuing club."""
        row = self.features(team)
        if row is None:
            return None
        if date.fromisoformat(row["features_available_on"]) > self.as_of:
            raise ValueError("Entry features postdate the forecast cutoff")
        if self.level == "population":
            return self.population_prior(f"{row['transition']} population")
        _, features = self._transition_features(row["transition"])
        if features is None:
            return self.population_prior(f"{row['transition']} population fallback")
        means, variances = [], []
        for dimension in DIMENSIONS:
            moments = []
            for index, timescale in enumerate(self.timescales):
                regression = self._regressions[row["transition"], dimension, index]
                x, xv = _feature_row(row, dimension, features, timescale)
                mean = float(x @ regression.coefficients)
                second = np.outer(regression.coefficients, regression.coefficients)
                variance = float(
                    regression.residual_variance
                    + x @ regression.covariance @ x
                    + np.sum(xv * (second + regression.covariance))
                )
                moments.append((mean, variance))
            weights = self.timescale_weights
            mean = float(weights @ [m for m, _ in moments])
            variance = float(weights @ [v + m**2 for m, v in moments] - mean**2)
            means.append(mean)
            variances.append(variance)
        covariance = np.diag(variances)
        correlation = self._residual_correlation.get(row["transition"], 0.0)
        covariance[0, 1] = covariance[1, 0] = correlation * np.sqrt(variances[0] * variances[1])
        return TeamPrior(np.array(means), covariance, f"{self.level} entry prior")

    def diagnostics(self) -> dict:
        result = {
            "as_of": str(self.as_of),
            "competition_id": self.competition,
            "target_season": self.target_season,
            "level": self.level,
            "training_label": self.label,
            "cohorts": len(self.rows),
            "last_training_season": max((r["season_id"] for r in self.rows), default=None),
            "timescales": [None if np.isinf(t) else t for t in self.timescales],
            "timescale_weights": self.timescale_weights.tolist(),
            "expected_memory_weight": {
                str(age): float(
                    self.timescale_weights @ [memory_weight(age, t) for t in self.timescales]
                )
                for age in (2, 3, 5, 10)
            },
            "transitions": {},
        }
        best = int(np.argmax(self.timescale_weights))
        for transition in self.transitions:
            rows, features = self._transition_features(transition)
            entry = {"cohorts": len(rows), "features": list(features or ())}
            if features is not None:
                entry["residual_correlation"] = self._residual_correlation.get(transition)
                for dimension in DIMENSIONS:
                    regression = self._regressions[transition, dimension, best]
                    entry[dimension] = {
                        "coefficients": regression.coefficients.tolist(),
                        "coefficient_sd": np.sqrt(np.diag(regression.covariance)).tolist(),
                        "residual_sd": float(np.sqrt(regression.residual_variance)),
                        "residual_sd_interval_05_95": list(regression.residual_sd_interval),
                    }
            result["transitions"][transition] = entry
        return result
