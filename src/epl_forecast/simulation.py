from dataclasses import dataclass
from datetime import date, datetime
from itertools import combinations
from zoneinfo import ZoneInfo

import numpy as np

from epl_forecast.competitions import COMPETITIONS
from epl_forecast.data.rules import LeagueRules, league_rules, reviewed_rules_evidence
from epl_forecast.models.base import ForecastModel
from epl_forecast.models.quality_tilt_scores import shift_scores
from epl_forecast.postseason import simulate_playoffs
from epl_forecast.schema import Fixture, Match


@dataclass(frozen=True)
class EuropeScenario:
    name: str
    champions_league_places: int
    fa_cup_winner: str
    efl_cup_winner: str

    def __post_init__(self) -> None:
        if self.champions_league_places not in (4, 5):
            raise ValueError("Supported European scenarios have four or five league UCL places")
        if not self.name or not self.fa_cup_winner or not self.efl_cup_winner:
            raise ValueError("A European scenario needs a name and both domestic cup winners")


def european_places(order: list[str], scenario: EuropeScenario) -> dict[str, set[str]]:
    champions = set(order[: scenario.champions_league_places])
    europa = set() if scenario.fa_cup_winner in champions else {scenario.fa_cup_winner}
    for team in order:
        if len(europa) == 2:
            break
        if team not in champions:
            europa.add(team)
    if scenario.efl_cup_winner not in champions | europa:
        conference = {scenario.efl_cup_winner}
    else:
        conference = {next(team for team in order if team not in champions | europa)}
    return {"champions_league": champions, "europa_league": europa, "conference_league": conference}


def decisive_group(
    order: list[int],
    start: int,
    end: int,
    teams: list[str],
    relegated: int,
    europe: EuropeScenario | None,
    boundaries: tuple[int, ...] = (),
) -> bool:
    if end - start < 2:
        return False
    if start == 0 or start < len(teams) - relegated < end:
        return True
    if any(start < boundary < end for boundary in boundaries):
        return True
    if europe is None:
        return False
    baseline = european_places([teams[i] for i in order], europe)
    for a, b in combinations(range(start, end), 2):
        alternate = list(order)
        alternate[a], alternate[b] = alternate[b], alternate[a]
        if european_places([teams[i] for i in alternate], europe) != baseline:
            return True
    return False


def rank_table(
    teams: list[str],
    points: np.ndarray,
    goal_difference: np.ndarray,
    goals_for: np.ndarray,
    head_points: np.ndarray,
    head_away_goals: np.ndarray,
    rng: np.random.Generator,
    relegated: int = 3,
    head_to_head: bool = True,
    europe: EuropeScenario | None = None,
    rules: LeagueRules | None = None,
    head_goals: np.ndarray | None = None,
    wins: np.ndarray | None = None,
    away_goals: np.ndarray | None = None,
    disciplinary_points: np.ndarray | None = None,
    serious_sendings_off: np.ndarray | None = None,
) -> tuple[list[int], list[tuple[int, int]], bool, bool]:
    efl = rules is not None and rules.ranking == "efl"
    boundaries = () if rules is None else (rules.automatic_promotion, rules.playoff_end)
    if rules is not None:
        relegated = rules.relegated
        head_to_head = rules.ranking == "pl_head_to_head"
    if efl and any(value is None for value in (head_goals, wins, away_goals)):
        raise ValueError("EFL ranking requires head-to-head goals, wins and away goals")
    order = list(map(int, np.lexsort((-goals_for, -goal_difference, -points))))
    tied_spans = []
    unresolved, used_head_to_head = False, False
    start = 0
    while start < len(teams):
        end = start + 1
        first = order[start]
        key = points[first], goal_difference[first], goals_for[first]
        while end < len(teams):
            team = order[end]
            if (points[team], goal_difference[team], goals_for[team]) != key:
                break
            end += 1
        group = order[start:end]
        critical = decisive_group(order, start, end, teams, relegated, europe, boundaries)
        if len(group) > 1 and efl:
            used_head_to_head = True
            metrics = {}
            for i in group:
                scored = int(head_goals[i, group].sum())
                conceded = int(head_goals[group, i].sum())
                metrics[i] = (
                    int(head_points[i, group].sum()),
                    scored - conceded,
                    scored,
                    int(wins[i]),
                    int(away_goals[i]),
                )
                if disciplinary_points is not None:
                    metrics[i] += (-int(disciplinary_points[i]),)
                    if serious_sendings_off is not None:
                        metrics[i] += (-int(serious_sendings_off[i]),)
            group.sort(key=lambda i: metrics[i], reverse=True)
            order[start:end] = group
            keys = [metrics[i] for i in group]
        elif len(group) > 1 and critical and head_to_head:
            used_head_to_head = True
            h2h_points = {i: int(head_points[i, group].sum()) for i in group}
            h2h_away = {i: int(head_away_goals[i, group].sum()) for i in group}
            group.sort(key=lambda i: (-h2h_points[i], -h2h_away[i]))
            order[start:end] = group
            keys = [(h2h_points[i], h2h_away[i]) for i in group]
        else:
            keys = [(0, 0)] * len(group)
        offset = 0
        while offset < len(group):
            stop = offset + 1
            while stop < len(group) and keys[stop] == keys[offset]:
                stop += 1
            if stop - offset > 1:
                left, right = start + offset, start + stop
                tied_spans.append((left, right))
                unresolved |= decisive_group(
                    order, left, right, teams, relegated, europe, boundaries
                )
                order[left:right] = list(map(int, rng.permutation(order[left:right])))
            offset = stop
        start = end
    return order, tied_spans, unresolved, used_head_to_head


def validate_schedule(
    teams: list[str],
    played: list[Match],
    remaining: list[Fixture],
    as_of: date,
    results_observed_at: datetime | None = None,
) -> None:
    fixtures = [m.fixture for m in played] + remaining
    competitions = {f.competition_id for f in fixtures}
    if len(competitions) != 1:
        raise ValueError("Simulation requires one competition")
    competition = next(iter(competitions))
    expected_teams = {c.competition_id: c.teams for c in COMPETITIONS}.get(competition)
    if expected_teams is None or len(teams) != expected_teams or len(set(teams)) != expected_teams:
        raise ValueError("Invalid league season participants")
    if len({f.season_id for f in fixtures}) != 1:
        raise ValueError("Simulation fixtures must belong to one season")
    pairs = [(f.home_team_id, f.away_team_id) for f in fixtures]
    expected = {(home, away) for home in teams for away in teams if home != away}
    if len(pairs) != len(expected) or len(set(pairs)) != len(expected) or set(pairs) != expected:
        raise ValueError("Simulation requires every ordered opponent pair exactly once")
    if results_observed_at is None:
        if any(match.available_on > as_of for match in played):
            raise ValueError("Played results must be available at the simulation cutoff")
    else:
        if (
            results_observed_at.tzinfo is None
            or results_observed_at.astimezone(ZoneInfo("Europe/London")).date() != as_of
        ):
            raise ValueError("Observed results must come from the model cutoff's calendar day")
        if any(match.fixture.match_date > as_of for match in played):
            raise ValueError("Played results postdate their snapshot observation")
    if any(fixture.match_date < as_of for fixture in remaining):
        raise ValueError("Remaining fixtures predate the simulation cutoff")


OUTCOME_NAMES = ("home", "draw", "away")
MINIMUM_CONDITIONAL_SAMPLES = 100
EVERY_TEAM = "every_team"


def conditional_impacts(
    outcomes: dict,
    event_paths: dict,
    teams: list[str],
    simulations: int,
    horizon_days: int,
    window: tuple[datetime, datetime] | None = None,
) -> dict:
    """Condition published season events on each fixture outcome, over the same paths.

    Every conditional is the mean of a team-event indicator over the subset of season
    paths where the fixture ended that way. Because those subsets partition the paths,
    the outcome-weighted conditionals must return the baseline exactly; that identity
    and the per-cell path counts are the checks reported here. Every club is measured
    against every fixture, from the same paths, because a result also moves clubs that
    do not play in it. These are conditional forecasts on one simulation, not causal
    effects of a result.
    """
    baselines = {event: values.mean(axis=0) for event, values in event_paths.items()}
    squares = {event: values * values for event, values in event_paths.items()}
    path = np.arange(simulations)
    fixtures, smallest = [], simulations
    for match_id, (fixture, codes) in sorted(outcomes.items()):
        counts = np.bincount(codes, minlength=3).astype(float)
        weights = (counts / simulations)[:, None]
        reached = (counts > 0)[:, None]
        divisor = np.where(counts > 0, counts, 1.0)[:, None]
        # One row per outcome, so a matrix product totals each outcome's paths at once.
        membership = np.zeros((3, simulations))
        membership[codes, path] = 1.0
        impacts = []
        for event, values in event_paths.items():
            baseline = baselines[event]
            conditional = (membership @ values) / divisor
            variance = np.maximum((membership @ squares[event]) / divisor - conditional**2, 0.0)
            error = np.sqrt(variance / divisor)
            movement = np.sqrt(
                (weights * np.where(reached, conditional - baseline, 0.0) ** 2).sum(axis=0)
            )
            spread = np.where(reached, conditional, np.nan)
            swing = np.nanmax(spread, axis=0) - np.nanmin(spread, axis=0)
            recovered = (weights * np.where(reached, conditional, 0.0)).sum(axis=0)
            if np.max(np.abs(recovered - baseline)) > 1e-9:
                raise RuntimeError(f"Conditional impacts do not total the baseline: {match_id}")
            for index, team in enumerate(teams):
                impacts.append(
                    {
                        "team_id": team,
                        "event": event,
                        "baseline": float(baseline[index]),
                        "conditional": {
                            name: float(conditional[outcome, index]) if counts[outcome] else None
                            for outcome, name in enumerate(OUTCOME_NAMES)
                        },
                        "standard_error": {
                            name: float(error[outcome, index]) if counts[outcome] else None
                            for outcome, name in enumerate(OUTCOME_NAMES)
                        },
                        "rms_movement": float(movement[index]),
                        "swing": float(swing[index]),
                        "sufficient_sample": bool(counts.min() >= MINIMUM_CONDITIONAL_SAMPLES),
                    }
                )
        impacts.sort(key=lambda row: row["rms_movement"], reverse=True)
        smallest = min(smallest, int(counts.min()))
        fixtures.append(
            {
                "match_id": match_id,
                "match_date": str(fixture.match_date),
                "home_team_id": fixture.home_team_id,
                "away_team_id": fixture.away_team_id,
                "outcome_counts": {
                    name: int(counts[outcome]) for outcome, name in enumerate(OUTCOME_NAMES)
                },
                "impacts": impacts,
                "top_rms_movement": impacts[0]["rms_movement"] if impacts else 0.0,
            }
        )
    fixtures.sort(key=lambda row: row["top_rms_movement"], reverse=True)
    return {
        "horizon_days": horizon_days,
        "simulations": simulations,
        "minimum_conditional_samples": MINIMUM_CONDITIONAL_SAMPLES,
        "smallest_outcome_count": int(smallest) if outcomes else 0,
        "coverage": EVERY_TEAM,
        "window_start": window[0].isoformat() if window else None,
        "window_end": window[1].isoformat() if window else None,
        "fixtures": fixtures,
        "basis": "Conditional forecasts aggregated from one season simulation, not causal effects of a result.",
    }


def simulate_season(
    model: ForecastModel,
    played: list[Match],
    remaining: list[Fixture],
    teams: list[str],
    as_of: date,
    simulations: int,
    seed: int,
    adjustments: list[dict] | None = None,
    europe: EuropeScenario | None = None,
    results_observed_at: datetime | None = None,
    playoff_winner: str | None = None,
    playoff_conditioning: str = "path",
    impact_fixtures: set[str] | None = None,
    impact_horizon_days: int = 7,
    impact_window: tuple[datetime, datetime] | None = None,
    log_rate_shifts: dict[str, float] | None = None,
) -> dict:
    if type(simulations) is not int or simulations < 1:
        raise ValueError("simulations must be a positive integer")
    if playoff_conditioning not in ("path", "marginal"):
        raise ValueError("Playoff conditioning is either path or marginal")
    teams = sorted(teams)
    validate_schedule(teams, played, remaining, as_of, results_observed_at)
    if model.as_of != as_of:
        raise ValueError("Model fit cutoff must equal the season simulation cutoff")
    adjustments = adjustments or []
    team_index = {team: index for index, team in enumerate(teams)}
    point_offsets = np.zeros(len(teams), dtype=int)
    for adjustment in adjustments:
        if date.fromisoformat(adjustment["known_on"]) > as_of:
            raise ValueError("Point adjustment was not known at the simulation cutoff")
        if adjustment["team_id"] not in team_index or type(adjustment["points"]) is not int:
            raise ValueError("Invalid point adjustment")
        if not adjustment.get("source"):
            raise ValueError("Point adjustments require a provenance source")
        point_offsets[team_index[adjustment["team_id"]]] += adjustment["points"]
    rng = np.random.default_rng(seed)
    points = np.tile(point_offsets, (simulations, 1))
    goals_for = np.zeros_like(points)
    goals_against = np.zeros_like(points)
    head_points = np.zeros((simulations, len(teams), len(teams)), dtype=np.int16)
    head_away = np.zeros_like(head_points)
    head_goals = np.zeros_like(head_points)
    wins = np.zeros_like(points)
    draws = np.zeros(simulations, dtype=int)

    def add_result(fixture: Fixture, home_goals, away_goals) -> None:
        h, a = team_index[fixture.home_team_id], team_index[fixture.away_team_id]
        home_goals, away_goals = np.asarray(home_goals), np.asarray(away_goals)
        home_points = 3 * (home_goals > away_goals) + (home_goals == away_goals)
        away_points = 3 * (away_goals > home_goals) + (home_goals == away_goals)
        points[:, h] += home_points
        points[:, a] += away_points
        goals_for[:, h] += home_goals
        goals_for[:, a] += away_goals
        goals_against[:, h] += away_goals
        goals_against[:, a] += home_goals
        head_points[:, h, a] += home_points
        head_points[:, a, h] += away_points
        head_away[:, a, h] += away_goals
        head_goals[:, h, a] += home_goals
        head_goals[:, a, h] += away_goals
        wins[:, h] += home_goals > away_goals
        wins[:, a] += away_goals > home_goals
        draws[:] += home_goals == away_goals

    for match in sorted(played, key=lambda m: m.fixture.match_id):
        add_result(match.fixture, match.home_goals, match.away_goals)
    season = (played[0].fixture if played else remaining[0]).season_id
    competition = (played[0].fixture if played else remaining[0]).competition_id
    rules = league_rules(competition, season)
    promotion = rules.promotes
    state_sampler = getattr(model, "sample_forecast_state", None)
    # A playoff bracket needs the same draws even when no league fixture is left.
    needs_states = bool(remaining) or (promotion and playoff_winner is None)
    states = state_sampler(rng, size=simulations) if state_sampler and needs_states else None
    if states is not None and (states.as_of != as_of or states.size != simulations):
        raise ValueError("Sampled forecast states must match the simulation cutoff and size")
    unknown_teams = set()
    known = getattr(model, "team_index", None)
    match_frequencies = []
    wanted = set(impact_fixtures or ())
    impact_outcomes = {}
    for fixture in sorted(remaining, key=lambda f: (f.match_date, f.match_id)):
        if known is not None:
            unknown_teams.update(
                t for t in (fixture.home_team_id, fixture.away_team_id) if t not in known
            )
        # A personnel shift is temporary: it moves this fixture's rates, not the sampled states.
        shift = (log_rate_shifts or {}).get(fixture.match_id, 0.0)
        if states is not None:
            goals = states.sample_scores(fixture, rng, log_rate_shift=shift)
        else:
            forecast = model.predict_match(fixture)
            if forecast.scores is None:
                raise ValueError("Season simulation requires a score-generating model")
            scores = shift_scores(forecast.scores, shift) if shift else forecast.scores
            goals = scores.sample(rng, simulations)
        if any(
            np.shape(g) != (simulations,)
            or not np.issubdtype(np.asarray(g).dtype, np.integer)
            or np.any(np.asarray(g) < 0)
            for g in goals
        ):
            raise ValueError("Score samples must be nonnegative integer arrays, one per path")
        add_result(fixture, *goals)
        if fixture.match_id in wanted:
            home, away = np.asarray(goals[0]), np.asarray(goals[1])
            impact_outcomes[fixture.match_id] = (
                fixture,
                np.where(home > away, 0, np.where(home == away, 1, 2)).astype(np.int8),
            )
        match_frequencies.append(
            {
                "match_id": fixture.match_id,
                "p_home": float(np.mean(goals[0] > goals[1])),
                "p_draw": float(np.mean(goals[0] == goals[1])),
                "p_away": float(np.mean(goals[0] < goals[1])),
            }
        )
    if not np.array_equal(goals_for.sum(axis=1), goals_against.sum(axis=1)):
        raise RuntimeError("Simulation goals do not balance")
    if not np.array_equal(
        points.sum(axis=1), 3 * len(teams) * (len(teams) - 1) - draws + point_offsets.sum()
    ):
        raise RuntimeError("Simulation points do not balance")
    goal_difference = goals_for - goals_against
    position_counts = np.zeros((len(teams), len(teams)))
    qualification = (
        {
            key: np.zeros(len(teams))
            for key in ("champions_league", "europa_league", "conference_league")
        }
        if europe is not None
        else {}
    )
    if europe is not None and competition != COMPETITIONS[0].competition_id:
        raise ValueError("European qualification scenarios apply to the Premier League")
    unresolved_count, head_to_head_count = 0, 0
    orders = np.empty((simulations, len(teams)), dtype=np.int16)
    position_events = (
        (
            "title_probability",
            "automatic_promotion_probability",
            "playoff_qualification_probability",
            "relegation_probability",
        )
        if promotion
        else (
            "title_probability",
            "top_four_probability",
            "top_five_probability",
            "relegation_probability",
        )
    )
    event_paths = (
        {key: np.zeros((simulations, len(teams))) for key in position_events}
        if impact_outcomes
        else {}
    )
    for sample in range(simulations):
        order, ties, unresolved, used_h2h = rank_table(
            teams,
            points[sample],
            goal_difference[sample],
            goals_for[sample],
            head_points[sample],
            head_away[sample],
            rng,
            rules=rules,
            head_goals=head_goals[sample],
            wins=wins[sample],
            away_goals=head_away[sample].sum(axis=1),
            europe=europe,
        )
        unresolved_count += unresolved
        head_to_head_count += used_h2h
        orders[sample] = order
        weights = np.eye(len(teams))
        for start, end in ties:
            weights[start:end, start:end] = 1 / (end - start)
        position_counts[order] += weights
        if event_paths:
            path_positions = np.zeros((len(teams), len(teams)))
            path_positions[order] = weights
            event_paths["title_probability"][sample] = path_positions[:, 0]
            event_paths["relegation_probability"][sample] = path_positions[
                :, -rules.relegated :
            ].sum(axis=1)
            if promotion:
                event_paths["automatic_promotion_probability"][sample] = path_positions[
                    :, : rules.automatic_promotion
                ].sum(axis=1)
                event_paths["playoff_qualification_probability"][sample] = path_positions[
                    :, rules.automatic_promotion : rules.playoff_end
                ].sum(axis=1)
            else:
                event_paths["top_four_probability"][sample] = path_positions[:, :4].sum(axis=1)
                event_paths["top_five_probability"][sample] = path_positions[:, :5].sum(axis=1)
        if europe is not None:
            for tournament, qualified in european_places([teams[i] for i in order], europe).items():
                for team in qualified & team_index.keys():
                    qualification[tournament][team_index[team]] += 1

    playoff_counts = np.zeros(len(teams))
    playoff_model = None
    if promotion:
        if playoff_winner is not None:
            if playoff_winner not in team_index:
                raise ValueError("Playoff winner must be a league participant")
            playoff_counts[team_index[playoff_winner]] = simulations
            playoff_model = {"format": "observed", "winner": playoff_winner}
        else:
            last_regular_day = max(f.match_date for f in [m.fixture for m in played] + remaining)
            winners, playoff_model = simulate_playoffs(
                model,
                orders,
                teams,
                competition,
                season,
                last_regular_day,
                rng,
                states if playoff_conditioning == "path" else None,
            )
            for winner, count in zip(*np.unique(winners, return_counts=True), strict=True):
                playoff_counts[team_index[str(winner)]] = count
        if event_paths:
            promoted = np.zeros((simulations, len(teams)))
            if playoff_winner is not None:
                promoted[:, team_index[playoff_winner]] = 1.0
            else:
                promoted[
                    np.arange(simulations), [team_index[str(winner)] for winner in winners]
                ] = 1.0
            event_paths["playoff_promotion_probability"] = promoted
            event_paths["promotion_probability"] = (
                event_paths["automatic_promotion_probability"] + promoted
            )

    def distribution(values: np.ndarray) -> dict[str, float]:
        outcomes, counts = np.unique(values, return_counts=True)
        return {
            str(int(value)): float(count / simulations)
            for value, count in zip(outcomes, counts, strict=True)
        }

    def central_intervals(values, probabilities=None):
        levels = (50, 80, 90)
        if probabilities is None:
            outcomes, counts = np.unique(values, return_counts=True)
            cdf = counts.cumsum() / simulations
        else:
            outcomes = np.arange(1, len(probabilities) + 1)
            cdf = np.asarray(probabilities).cumsum()
        result = {}
        for level in levels:
            tail = (1 - level / 100) / 2
            result[str(level)] = list(map(int, outcomes[np.searchsorted(cdf, [tail, 1 - tail])]))
        return result

    rows = []
    for index, team in enumerate(teams):
        positions = position_counts[index] / simulations
        ranks = np.arange(1, len(teams) + 1)
        mean_position = float(positions @ ranks)
        position_intervals = central_intervals(None, positions)
        points_intervals = central_intervals(points[:, index])
        row = {
            "team_id": team,
            "mean_position": mean_position,
            "position_sd": float(np.sqrt(((ranks - mean_position) ** 2) @ positions)),
            "position_quantiles_05_50_95": list(
                map(int, np.searchsorted(positions.cumsum(), [0.05, 0.5, 0.95]) + 1)
            ),
            "median_position": int(np.searchsorted(positions.cumsum(), 0.5) + 1),
            "position_intervals": position_intervals,
            "position_probabilities": list(positions),
            "mean_points": float(points[:, index].mean()),
            "points_quantiles_05_50_95": list(np.quantile(points[:, index], [0.05, 0.5, 0.95])),
            "median_points": int(np.quantile(points[:, index], 0.5, method="inverted_cdf")),
            "points_intervals": points_intervals,
            "points_distribution": distribution(points[:, index]),
            "mean_goal_difference": float(goal_difference[:, index].mean()),
            "goal_difference_distribution": distribution(goal_difference[:, index]),
            "title_probability": float(positions[0]),
            "top_four_probability": float(positions[:4].sum()),
            "top_five_probability": float(positions[:5].sum()),
            "relegation_probability": float(positions[-rules.relegated :].sum()),
        }
        if promotion:
            row["automatic_promotion_probability"] = float(
                positions[: rules.automatic_promotion].sum()
            )
            row["playoff_qualification_probability"] = float(
                positions[rules.automatic_promotion : rules.playoff_end].sum()
            )
            row["playoff_promotion_probability"] = float(playoff_counts[index] / simulations)
            row["promotion_probability"] = (
                row["automatic_promotion_probability"] + row["playoff_promotion_probability"]
            )
            row.pop("top_four_probability")
            row.pop("top_five_probability")
        if europe is not None:
            row["conditional_europe_probabilities"] = {
                key: float(values[index] / simulations) for key, values in qualification.items()
            }
        rows.append(row)
    for event, values in event_paths.items():
        published = np.array([row[event] for row in rows])
        if np.max(np.abs(values.mean(axis=0) - published)) > 1e-9:
            raise RuntimeError(f"Per-path event indicators disagree with the published {event}")
    impacts = (
        conditional_impacts(
            impact_outcomes,
            event_paths,
            teams,
            simulations,
            impact_horizon_days,
            impact_window,
        )
        if impact_outcomes
        else None
    )
    return {
        "competition_id": competition,
        "match_impacts": impacts,
        "season_id": season,
        "as_of": str(as_of),
        "results_observed_at": results_observed_at.isoformat() if results_observed_at else None,
        "simulations": simulations,
        "seed": seed,
        "played_matches": len(played),
        "remaining_matches": len(remaining),
        "match_frequencies": match_frequencies,
        "state_uncertainty": "posterior" if states is not None else "fixed",
        "future_state_evolution": bool(getattr(states, "evolves_future_states", False)),
        "teams": rows,
        "unseen_teams": sorted(unknown_teams),
        "point_adjustments": adjustments,
        "ranking_rules": rules.ranking,
        "ranking_rules_evidence": reviewed_rules_evidence(competition, season),
        "playoff_model": playoff_model,
        "disciplinary_tiebreaks_available": False if rules.ranking == "efl" else None,
        "head_to_head_applied_rate": head_to_head_count / simulations,
        "unresolved_decisive_tie_rate": unresolved_count / simulations,
        "assumptions": [
            (
                "One dynamics specification and current joint state per path; calendar-time "
                "latent transitions and independent match tempo shocks continue through fixtures. "
                "Simulated scores do not update the sampled latent states."
                if getattr(states, "evolves_future_states", False)
                else "One joint posterior state per season path, reused across fixtures. "
                "Includes strength uncertainty and match randomness; no future state evolution."
                if states is not None
                else "Fixed fitted team strengths; independent match outcomes "
                "conditional on fitted state."
            ),
            (
                "Captured full-time results are fixed, including today; fitting excludes today. "
                "Fixture dates follow the captured schedule; fixed-state models can use "
                "cutoff-date placeholders for unscheduled fixtures."
                if results_observed_at
                else "No future result labels used. "
                "Historical fixture dates are retrospectively recorded."
            ),
            "Nondecisive shared positions split mass across occupied ranks for reporting.",
            (
                "EFL disciplinary tiebreak data are unavailable. Remaining ties split rank mass equally; "
                "this is an uncertainty assumption, not an application of disciplinary rules."
                if rules.ranking == "efl"
                else "Unresolved decisive ties assume equal playoff chances; playoff model not estimated."
            ),
            "Points adjustments include only supplied sanctions known at the cutoff.",
        ]
        + (
            [
                f"European qualification is conditional on scenario: {europe.name}.",
                "Scenario assumes no extra English UEFA titleholders or eligibility exclusions.",
            ]
            if europe
            else [
                "Playoff promotion simulates the applicable bracket conditional on every "
                "regular-season path, on that path's own latent team states when the "
                "model supplies them."
            ]
            if promotion
            else ["Top-four/five probabilities are table positions, not European qualification."]
        ),
        "europe_scenario": None
        if europe is None
        else {
            "name": europe.name,
            "champions_league_places": europe.champions_league_places,
            "fa_cup_winner": europe.fa_cup_winner,
            "efl_cup_winner": europe.efl_cup_winner,
        },
    }
