"""Realized personnel continuity and temporary Quality adjustments."""

import copy
from collections import defaultdict

import numpy as np

from epl_forecast.models.quality_tilt_scores import ScoreMixture

WINDOW = 8
REFERENCE_MINUTES = 90
FULL_RECENT_MINUTES = 700
FULL_STARTING_MINUTES = 990


def lineup_minutes(rows, starters=False):
    values = defaultdict(dict)
    for row in rows:
        players = values[row["match_id"], row["team_id"]]
        value = REFERENCE_MINUTES if starters and row["starts"] else 0
        if not starters:
            value = min(int(row["minutes"]), REFERENCE_MINUTES)
        players[row["player_id"]] = players.get(row["player_id"], 0) + value
    return values


def realized_continuity(matches, appearance_rows, window=WINDOW):
    """Return starting-XI discontinuity from recent player minutes."""
    recent = lineup_minutes(appearance_rows)
    target = lineup_minutes(appearance_rows, starters=True)
    complete_recent = {
        key: players
        for key, players in recent.items()
        if sum(players.values()) >= FULL_RECENT_MINUTES
    }
    complete_target = {
        key: players
        for key, players in target.items()
        if sum(players.values()) >= FULL_STARTING_MINUTES
    }
    by_team = defaultdict(list)
    for match in sorted(matches, key=lambda item: (item.fixture.match_date, item.fixture.match_id)):
        for team in (match.fixture.home_team_id, match.fixture.away_team_id):
            by_team[team].append(match)
    result = {}
    for team, games in by_team.items():
        for index, match in enumerate(games):
            previous = [
                game for game in games[:index] if game.fixture.match_date < match.fixture.match_date
            ][-window:]
            histories = [complete_recent.get((game.fixture.match_id, team)) for game in previous]
            starters = complete_target.get((match.fixture.match_id, team))
            if starters is None or len(histories) < window or any(row is None for row in histories):
                result[match.fixture.match_id, team] = None
                continue
            weights = defaultdict(float)
            for players in histories:
                for player, minutes in players.items():
                    weights[player] += minutes
            represented = sum(weight for player, weight in weights.items() if player in starters)
            result[match.fixture.match_id, team] = 1 - represented / sum(weights.values())
    return result


def quality_shift(d_home, d_away, kappa):
    delta = kappa * (d_away - d_home)
    return np.array([delta, -delta])


def shifted_scores(scores, shift):
    """Copy a score distribution and shift its joint log-rate mean."""
    if isinstance(scores, ScoreMixture):
        return ScoreMixture(
            [shifted_scores(component, shift) for component in scores.components], scores.weights
        )
    shifted = copy.copy(scores)
    factors = np.exp(shift)
    shifted.log_mean = scores.log_mean + shift
    shifted.home_rates = scores.home_rates * factors[0]
    shifted.away_rates = scores.away_rates * factors[1]
    shifted.home_rate = float(shifted.weights @ shifted.home_rates)
    shifted.away_rate = float(shifted.weights @ shifted.away_rates)
    return shifted
