"""Cutoff-safe availability rules for the personnel mean experiment."""

import numpy as np


def fpl_probability(row):
    chance = row.get("chance_next_round")
    if chance is not None:
        return float(chance) / 100
    return {"a": 1.0, "d": 0.5, "i": 0.0, "s": 0.0, "u": 0.0}.get(row.get("status"))


def api_probability(row):
    return {"unavailable": 0.0, "doubtful": 0.5}.get(row.get("status"))


def resolve_availability(in_squad, evidence):
    """Combine squad membership and explicit provider signals."""
    values = [item["probability"] for item in evidence]
    if any(value is None for value in values):
        return None, "unknown provider status"
    if not in_squad:
        if any(value > 0 for value in values):
            return None, "provider evidence conflicts with the captured squad"
        return 0.0, "outside the captured squad"
    if values and not np.allclose(values, values[0], atol=1e-12, rtol=0):
        return None, "provider probabilities conflict"
    if values:
        return values[0], "provider availability"
    return 1.0, "current squad member without contrary evidence"


def expected_discontinuity(weights, availability):
    if not weights or any(availability.get(player) is None for player in weights):
        return None
    total = sum(weights.values())
    represented = sum(weight * availability[player] for player, weight in weights.items())
    return 1 - represented / total
