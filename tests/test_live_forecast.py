import json
import math

import numpy as np
import pytest

from epl_forecast.live_forecast import forecast_probability_stages
from epl_forecast.models.base import Forecast
from epl_forecast.models.poisson import IndependentPoisson, PoissonMixture


def test_forecast_artifact_keeps_the_three_probability_stages():
    scores = PoissonMixture(np.log([1.6, 1.1]), np.zeros((2, 2)))
    prediction = Forecast(scores.outcome_probabilities(), scores)
    quote = {
        "family": "closing",
        "retrieved_at": "2026-09-11T00:00:00+00:00",
        "home_odds": 2.0,
        "draw_odds": 3.5,
        "away_odds": 4.0,
    }
    stages, adjusted_scores, adjusted_probabilities, assistance = forecast_probability_stages(
        prediction, 10, 0.2, quote, {"market_weight": 0.25}
    )

    assert stages["unadjusted"]["score_distribution"]["home_rate"] == 1.6
    assert stages["personnel_adjusted"]["score_distribution"]["home_rate"] == pytest.approx(
        1.6 * math.exp(0.2)
    )
    assert adjusted_scores.home_rate == pytest.approx(1.6 * math.exp(0.2))
    assert tuple(
        stages["personnel_adjusted"][f"p_{side}"] for side in ("home", "draw", "away")
    ) == pytest.approx(adjusted_probabilities)
    assert stages["market_assisted"]["score_generating"] is False
    assert "score_distribution" not in stages["market_assisted"]
    assert stages["market_assisted"]["market_probabilities"] == assistance["market_probabilities"]


def test_a_neutral_personnel_stage_equals_the_unadjusted_stage():
    scores = IndependentPoisson(1.4, 1.0)
    prediction = Forecast(scores.outcome_probabilities(), scores)
    stages, _, _, _ = forecast_probability_stages(prediction, 10)
    for side in ("home", "draw", "away"):
        assert stages["unadjusted"][f"p_{side}"] == stages["personnel_adjusted"][f"p_{side}"]


class Catalog:
    """A fake R2 data bucket that holds every batch published in one directory."""

    def __init__(self, directory):
        self.directory = directory

    def get_json(self, key, default=None):
        if key != "state/manifests.json":
            return default
        manifests = sorted(self.directory.glob("manifests/*.json"))
        return {"manifests": [json.loads(path.read_text()) for path in manifests]}

    def uri(self, key):
        return str(self.directory / key)

    def configure_duckdb(self, connection):
        pass


def catalog(directory):
    return Catalog(directory)


def test_a_postponed_fixture_waits_on_the_cutoff_day(tmp_path):
    from datetime import UTC, date, datetime

    from epl_forecast.datasets import publish
    from epl_forecast.live import load_live_season

    def fixture(home, away, status, day, goals=None):
        return {
            "match_id": f"eng-league-one:2026-2027:{home}:{away}",
            "competition_id": "eng-league-one",
            "season_id": "2026-2027",
            "stage": "regular",
            "home_team_id": home,
            "away_team_id": away,
            "match_date": day,
            "kickoff_time": f"{day}T14:00:00+00:00",
            "status": status,
            "home_goals": goals,
            "away_goals": 0 if goals is not None else None,
        }

    evidence = {
        "provider": "api_football",
        "retrieved_at": "2026-09-10T10:00:00+00:00",
        "evidence_basis": "captured",
        "source_sha256": "a" * 64,
        "context": {"endpoint": "fixtures"},
    }
    rows = [
        fixture("oxford-united", "reading", "postponed", "2026-09-08"),
        fixture("reading", "oxford-united", "finished", "2026-08-15", goals=1),
    ]
    publish(tmp_path, evidence, {"fixtures": rows})
    cutoff = datetime(2026, 9, 11, 12, tzinfo=UTC)
    live = load_live_season(cutoff, "eng-league-one", "2026-2027", catalog(tmp_path))
    (waiting,) = live.remaining
    assert waiting.match_date == date(2026, 9, 11)
    assert live.details[waiting.match_id]["status"] == "unscheduled"
    assert len(live.played) == 1


def test_a_match_that_started_without_a_result_waits_on_the_cutoff_day(tmp_path):
    """An overdue match keeps the season simulable; its own date is already past."""
    from datetime import UTC, date, datetime

    from epl_forecast.datasets import publish
    from epl_forecast.live import load_live_season

    def fixture(home, away, status, day, goals=None):
        return {
            "match_id": f"eng-league-one:2026-2027:{home}:{away}",
            "competition_id": "eng-league-one",
            "season_id": "2026-2027",
            "stage": "regular",
            "home_team_id": home,
            "away_team_id": away,
            "match_date": day,
            "kickoff_time": f"{day}T14:00:00+00:00",
            "status": status,
            "home_goals": goals,
            "away_goals": 0 if goals is not None else None,
        }

    evidence = {
        "provider": "api_football",
        "retrieved_at": "2026-09-10T10:00:00+00:00",
        "evidence_basis": "captured",
        "source_sha256": "a" * 64,
        "context": {"endpoint": "fixtures"},
    }
    rows = [
        fixture("oxford-united", "reading", "in_progress", "2026-09-10"),
        fixture("reading", "oxford-united", "finished", "2026-08-15", goals=1),
    ]
    publish(tmp_path, evidence, {"fixtures": rows})
    live = load_live_season(
        datetime(2026, 9, 11, 12, tzinfo=UTC), "eng-league-one", "2026-2027", catalog(tmp_path)
    )
    (waiting,) = live.remaining
    assert waiting.match_date == date(2026, 9, 11)
    assert live.details[waiting.match_id]["match_date"] == "2026-09-10"
    assert live.details[waiting.match_id]["status"] == "in_progress"
