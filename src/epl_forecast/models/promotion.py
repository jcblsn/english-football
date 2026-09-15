from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

import numpy as np
from numpy.polynomial.legendre import leggauss
from scipy.linalg import cho_factor, cho_solve
from scipy.special import logsumexp

from epl_forecast.competitions import ENTRY_SOURCE_COMPETITIONS
from epl_forecast.models.baselines import AttackDefensePoisson
from epl_forecast.schema import Match

PL = "eng-premier-league"
CHAMPIONSHIP = "eng-championship"
FIELD_SIZES = {c.competition_id: c.teams for c in ENTRY_SOURCE_COMPETITIONS}


@dataclass(frozen=True)
class TeamPrior:
    mean: np.ndarray
    covariance: np.ndarray
    source: str


@dataclass(frozen=True)
class SeasonStrengths:
    season_id: str
    available_on: date
    teams: dict[str, TeamPrior]
    intercept: float
    home_advantage: float


@lru_cache(maxsize=96)
def season_strengths(matches: tuple[Match, ...]) -> SeasonStrengths:
    """Division-relative season summaries, with centered Laplace marginal variances."""
    cutoff = max(m.available_on for m in matches)
    model = AttackDefensePoisson(ridge=2.0, half_life_days=None).fit(list(matches), cutoff)
    n = len(model.team_index)
    design = np.zeros((2 * len(matches), 2 + 2 * n))
    for row, match in enumerate(matches):
        h, a = (
            model.team_index[t] for t in (match.fixture.home_team_id, match.fixture.away_team_id)
        )
        design[2 * row, [0, 1, 2 + h, 2 + n + a]] = [1, 1, 1, -1]
        design[2 * row + 1, [0, 2 + a, 2 + n + h]] = [1, 1, -1]
    design[:, 2 : 2 + n] -= design[:, 2 : 2 + n].mean(axis=1, keepdims=True)
    design[:, 2 + n :] -= design[:, 2 + n :].mean(axis=1, keepdims=True)
    parameters = np.r_[model.intercept, model.home_advantage, model.attack, model.defense]
    rates = np.exp(design @ parameters)
    precision = (design.T * rates) @ design + np.diag(np.r_[0.0, 0.0, np.full(2 * n, 2.0)])
    bh, ba = np.exp(model.intercept + model.home_advantage), np.exp(model.intercept)
    precision[:2, :2] += [[bh + ba, bh], [bh, bh]]
    covariance = cho_solve(cho_factor(precision), np.eye(len(parameters)))
    center = np.eye(n) - np.ones((n, n)) / n
    teams = {}
    for team, i in model.team_index.items():
        transform = np.zeros((2, len(parameters)))
        transform[0, 2 : 2 + n] = center[i]
        transform[1, 2 + n :] = center[i]
        teams[team] = TeamPrior(
            np.array([model.attack[i], model.defense[i]]),
            transform @ covariance @ transform.T,
            "division season scores",
        )
    return SeasonStrengths(
        matches[0].fixture.season_id,
        cutoff,
        teams,
        float(model.intercept),
        float(model.home_advantage),
    )


def completed_seasons(
    matches: list[Match], as_of: date
) -> dict[tuple[str, str], tuple[Match, ...]]:
    groups = defaultdict(list)
    for match in matches:
        if match.available_on <= as_of and match.fixture.competition_id in FIELD_SIZES:
            groups[match.fixture.competition_id, match.fixture.season_id].append(match)
    result = {}
    for (competition, season), rows in groups.items():
        n = FIELD_SIZES[competition]
        pairs = {(m.fixture.home_team_id, m.fixture.away_team_id) for m in rows}
        teams = {t for pair in pairs for t in pair}
        if len(rows) == len(pairs) == n * (n - 1) and len(teams) == n:
            result[competition, season] = tuple(
                sorted(rows, key=lambda m: (m.fixture.match_date, m.fixture.match_id))
            )
    return result


def preceding_season(season: str) -> str:
    year = int(season[:4])
    return f"{year - 1}-{year}"


def early_strength(goals: int, exposure: float, defense: bool = False) -> tuple[float, float]:
    """Scalar log-relative scoring rate with a weak N(0, 1) prior."""
    value = 0.0
    for _ in range(40):
        expected = exposure * np.exp(value)
        step = (expected - goals + value) / (expected + 1)
        value -= np.clip(step, -1, 1)
        if abs(step) < 1e-10:
            break
    return (-value if defense else value), float(1 / (exposure * np.exp(value) + 1))


def entry_label(
    target: SeasonStrengths, target_matches: tuple[Match, ...], team: str, first: int = 10
) -> dict:
    """A club's opening target-division strength, exposure-adjusted for its opponents.

    This is the label every entry prior is judged against, so one definition
    serves the division bridges and the transition-aware entry priors alike.
    """
    games = [m for m in target_matches if team in (m.fixture.home_team_id, m.fixture.away_team_id)][
        :first
    ]
    scored, conceded, points, exposure_for, exposure_against = 0, 0, 0, 0.0, 0.0
    for match in games:
        home = match.fixture.home_team_id == team
        opponent = target.teams[match.fixture.away_team_id if home else match.fixture.home_team_id]
        gf, ga = (
            (match.home_goals, match.away_goals) if home else (match.away_goals, match.home_goals)
        )
        scored += gf
        conceded += ga
        points += 3 * (gf > ga) + (gf == ga)
        exposure_for += np.exp(target.intercept + home * target.home_advantage - opponent.mean[1])
        exposure_against += np.exp(
            target.intercept + (not home) * target.home_advantage + opponent.mean[0]
        )
    attack, attack_var = early_strength(scored, exposure_for)
    defense, defense_var = early_strength(conceded, exposure_against, defense=True)
    return {
        "team_id": team,
        "season_id": target.season_id,
        "entry_attack": float(attack),
        "entry_defense": float(defense),
        "entry_attack_variance": attack_var,
        "entry_defense_variance": defense_var,
        "first_ten_matches": len(games),
        "first_ten_points": int(points),
        "first_ten_goals_for": scored,
        "first_ten_goals_against": conceded,
    }


@lru_cache(maxsize=192)
def division_cohort(
    source_matches: tuple[Match, ...], target_matches: tuple[Match, ...]
) -> tuple[dict, ...]:
    """Clubs in both seasons: their source-division summary beside their first ten target matches.

    Direction lives entirely in the two arguments, so the same summary serves
    promotion into the Premier League and relegation into the Championship.
    """
    source, target = season_strengths(source_matches), season_strengths(target_matches)
    rows = []
    for team in sorted(source.teams.keys() & target.teams.keys()):
        label = entry_label(target, target_matches, team)
        rows.append(
            {
                "team_id": team,
                "season_id": target.season_id,
                "available_on": str(max(source.available_on, target.available_on)),
                "source_attack": float(source.teams[team].mean[0]),
                "source_defense": float(source.teams[team].mean[1]),
                "source_attack_variance": float(source.teams[team].covariance[0, 0]),
                "source_defense_variance": float(source.teams[team].covariance[1, 1]),
                **{k: v for k, v in label.items() if k not in ("team_id", "season_id")},
            }
        )
    return tuple(rows)


@dataclass(frozen=True)
class BridgeRegression:
    coefficients: np.ndarray
    covariance: np.ndarray
    residual_sd: float
    residual_sd_interval: tuple[float, float] = (0.0, 0.6)


def fit_bridge_regression(rows: list[dict], dimension: str) -> BridgeRegression:
    beta_prior = np.diag([0.6**2, 1.0])
    if not rows:
        return BridgeRegression(np.zeros(2), beta_prior, 0.3)
    x = np.array([r[f"source_{dimension}"] for r in rows])
    xv = np.array([r[f"source_{dimension}_variance"] for r in rows])
    y = np.array([r[f"entry_{dimension}"] for r in rows])
    yv = np.array([r[f"entry_{dimension}_variance"] for r in rows])
    design = np.column_stack([np.ones(len(rows)), x])
    input_noise = np.zeros(len(rows))
    nodes, quadrature_weights = leggauss(61)
    scales = (nodes + 1) * 0.75
    for _ in range(3):
        log_weights, conditional_means, conditional_covariances = [], [], []
        for sd, quadrature_weight in zip(scales, quadrature_weights, strict=True):
            variance = yv + input_noise + sd**2
            marginal = np.diag(variance) + design @ beta_prior @ design.T
            factor = cho_factor(marginal)
            log_weights.append(
                np.log(quadrature_weight)
                - np.log(np.diag(factor[0])).sum()
                - 0.5 * (y @ cho_solve(factor, y))
                - 0.5 * (sd / 0.3) ** 2
            )
            precision = np.linalg.inv(beta_prior) + (design.T / variance) @ design
            conditional_covariance = np.linalg.inv(precision)
            conditional_covariances.append(conditional_covariance)
            conditional_means.append(conditional_covariance @ (design.T @ (y / variance)))
        weights = np.exp(np.array(log_weights) - logsumexp(log_weights))
        conditional_means = np.array(conditional_means)
        coefficients = weights @ conditional_means
        deviations = conditional_means - coefficients
        covariance = np.einsum("i,ijk->jk", weights, conditional_covariances)
        covariance += (deviations.T * weights) @ deviations
        input_noise = xv * (coefficients[1] ** 2 + covariance[1, 1])
    interval = np.interp([0.05, 0.95], np.cumsum(weights), scales)
    return BridgeRegression(
        coefficients, covariance, float(np.sqrt(weights @ scales**2)), tuple(map(float, interval))
    )


class DivisionBridge:
    """Empirical-Bayes entry prior for a club crossing one division boundary.

    A subclass names the direction. The regression is fitted on earlier realized
    cohorts that crossed the same boundary, so it estimates how the source
    division's relative attack and defence translate into the target division
    rather than asserting that a club keeps its strength across the divide.
    """

    source_competition = CHAMPIONSHIP
    target_competition = PL
    label = "Championship promotion bridge"

    def __init__(self, matches: list[Match], as_of: date, target_season: str) -> None:
        self.as_of, self.target_season = as_of, target_season
        seasons = completed_seasons(matches, as_of)
        self.cohorts = []
        for (competition, season), rows in sorted(seasons.items()):
            if competition != self.target_competition or season >= target_season:
                continue
            source = seasons.get((self.source_competition, preceding_season(season)))
            if source:
                self.cohorts.extend(division_cohort(source, rows))
        source = seasons.get((self.source_competition, preceding_season(target_season)))
        self.source = season_strengths(source) if source else None
        self.regressions = [fit_bridge_regression(self.cohorts, d) for d in ("attack", "defense")]

    def prior(self, team: str, use_performance: bool = True) -> TeamPrior | None:
        if self.source is None or team not in self.source.teams:
            return None
        source = self.source.teams[team]
        means, variances = [], []
        for i, (dimension, regression) in enumerate(
            zip(("attack", "defense"), self.regressions, strict=True)
        ):
            x, xv = source.mean[i], source.covariance[i, i]
            if not use_performance and self.cohorts:
                values = np.array([r[f"source_{dimension}"] for r in self.cohorts])
                x, xv = float(values.mean()), float(values.var())
            design = np.array([1.0, x])
            means.append(float(design @ regression.coefficients))
            variances.append(
                float(
                    regression.residual_sd**2
                    + design @ regression.covariance @ design
                    + xv * (regression.coefficients[1] ** 2 + regression.covariance[1, 1])
                )
            )
        return TeamPrior(np.array(means), np.diag(variances), self.label)

    def diagnostics(self) -> dict:
        return {
            "as_of": str(self.as_of),
            "target_season": self.target_season,
            "source_competition": self.source_competition,
            "target_competition": self.target_competition,
            "cohorts": len(self.cohorts),
            "last_target_season": max((r["season_id"] for r in self.cohorts), default=None),
            "dimensions": {
                d: {
                    "intercept": float(r.coefficients[0]),
                    "slope": float(r.coefficients[1]),
                    "coefficient_sd": np.sqrt(np.diag(r.covariance)).tolist(),
                    "residual_sd": r.residual_sd,
                    "residual_sd_interval_05_95": list(r.residual_sd_interval),
                }
                for d, r in zip(("attack", "defense"), self.regressions, strict=True)
            },
        }


class PromotionBridge(DivisionBridge):
    """Championship season summaries into a promoted club's first Premier League matches."""


class RelegationBridge(DivisionBridge):
    """Premier League season summaries into a relegated club's first Championship matches."""

    source_competition = PL
    target_competition = CHAMPIONSHIP
    label = "Premier League relegation bridge"
