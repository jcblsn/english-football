import pytest

from epl_forecast.research.availability import (
    api_probability,
    expected_discontinuity,
    fpl_probability,
    resolve_availability,
)


def test_provider_probability_rules():
    assert api_probability({"status": "unavailable"}) == 0
    assert api_probability({"status": "doubtful"}) == 0.5
    assert api_probability({"status": "unknown"}) is None
    assert fpl_probability({"status": "d", "chance_next_round": 75}) == 0.75
    assert fpl_probability({"status": "d", "chance_next_round": None}) == 0.5


def test_availability_preserves_conflicts_and_missing_status():
    assert resolve_availability(True, []) == (
        1.0,
        "current squad member without contrary evidence",
    )
    assert resolve_availability(False, []) == (0.0, "outside the captured squad")
    assert resolve_availability(
        True,
        [
            {"probability": 0.0},
            {"probability": 1.0},
        ],
    ) == (None, "provider probabilities conflict")
    assert resolve_availability(True, [{"probability": None}]) == (
        None,
        "unknown provider status",
    )


def test_expected_discontinuity_uses_recent_minute_weights():
    weights = {"available": 540, "missing": 180}
    availability = {"available": 1.0, "missing": 0.0}
    assert expected_discontinuity(weights, availability) == pytest.approx(0.25)
    availability["missing"] = None
    assert expected_discontinuity(weights, availability) is None
