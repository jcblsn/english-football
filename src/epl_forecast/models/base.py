from dataclasses import dataclass
from datetime import date
from typing import Protocol, Self

import numpy as np

from epl_forecast.schema import Fixture, Match


class ScoreDistribution(Protocol):
    def outcome_probabilities(self) -> tuple[float, float, float]: ...

    def log_probability(self, home_goals: int, away_goals: int) -> float: ...

    def sample(self, rng: np.random.Generator, size: int) -> tuple[np.ndarray, np.ndarray]: ...


@dataclass(frozen=True)
class Forecast:
    probabilities: tuple[float, float, float]
    scores: ScoreDistribution | None = None

    def __post_init__(self) -> None:
        p = np.asarray(self.probabilities)
        if p.shape != (3,) or not np.all(np.isfinite(p)) or np.any(p < 0):
            raise ValueError("Forecast requires three finite, nonnegative H/D/A probabilities")
        if not np.isclose(p.sum(), 1.0, atol=1e-10, rtol=0):
            raise ValueError("Forecast probabilities must sum to one")


def selected_mask(size: int, paths) -> np.ndarray | None:
    """A boolean over all draws, or None when every draw is wanted."""
    if paths is None:
        return None
    mask = np.zeros(size, dtype=bool)
    mask[np.asarray(paths, dtype=int)] = True
    return mask


class ForecastModel(Protocol):
    as_of: date | None

    def fit(self, matches: list[Match], as_of: date) -> Self: ...

    def predict_match(self, fixture: Fixture) -> Forecast: ...


class SampledForecastStates(Protocol):
    """Each array index is one joint model-state draw, reused across all fixtures.

    ``paths`` selects the draws a fixture is played out for, which a postseason bracket
    needs because each path reaches a different tie. States that evolve in calendar time
    still advance every draw to the fixture's date, so a later selection resumes from
    the right place; only the returned scores are restricted.
    """

    as_of: date
    size: int

    def sample_scores(
        self,
        fixture: Fixture,
        rng: np.random.Generator,
        paths: np.ndarray | None = None,
        log_rate_shift: float = 0.0,
    ) -> tuple[np.ndarray, np.ndarray]:
        """``log_rate_shift`` adds to the home and subtracts from the away log rate of this
        fixture only. The sampled states do not change."""
        ...


class ProbabilisticForecastModel(ForecastModel, Protocol):
    def sample_forecast_state(
        self, rng: np.random.Generator, size: int = 1
    ) -> SampledForecastStates: ...
