import math
from datetime import UTC, datetime, time, timedelta

from epl_forecast.competitions import competition
from epl_forecast.live import LONDON, LiveSeason, timestamp
from epl_forecast.market import market_assisted_probabilities
from epl_forecast.models.base import ForecastModel
from epl_forecast.models.quality_tilt_scores import shift_scores
from epl_forecast.personnel import COMPETITIONS, HORIZON, KAPPA
from epl_forecast.schema import Match
from epl_forecast.simulation import EuropeScenario, simulate_season

UNSCHEDULED_PLACEHOLDER = (
    "Postponed or undated fixtures are simulated on the model cutoff day until the provider "
    "re-dates them; re-dating moves only the date their latent states are evolved to."
)
STARTED_WITHOUT_RESULT = ("in_progress", "awaiting_result")
UNSETTLED_PLACEHOLDER = (
    "A match that started without a full-time result is simulated on the cutoff day as a match "
    "that is not played. The forecast does not use the current score, and it does not forecast "
    "a match in play. The projection of that match, and of the clubs in it, is a pre-match "
    "projection that is one match behind the live table."
)


def score_stage(scores, max_goals, probabilities=None):
    """One score-generating probability stage with its complete finite score grid."""
    probabilities = scores.outcome_probabilities() if probabilities is None else probabilities
    grid, tail = scores.grid(max_goals)
    return {
        "p_home": float(probabilities[0]),
        "p_draw": float(probabilities[1]),
        "p_away": float(probabilities[2]),
        "score_distribution": {
            "home_rate": float(scores.home_rate),
            "away_rate": float(scores.away_rate),
            "grid_home_rows_away_columns": grid.tolist(),
            "omitted_probability": float(tail),
            **(
                {"uncertainty_components": scores.uncertainty_components()}
                if hasattr(scores, "uncertainty_components")
                else {}
            ),
        },
    }


def forecast_probability_stages(prediction, max_goals, shift=None, quote=None, market_pool=None):
    """Keep model, personnel-adjusted, and market-assisted outputs as separate stages."""
    unadjusted_scores = prediction.scores
    unadjusted = {
        "parent_stage": "model_state",
        "score_generating": True,
        **score_stage(unadjusted_scores, max_goals, prediction.probabilities),
    }
    adjusted_scores = (
        shift_scores(unadjusted_scores, shift) if shift is not None else unadjusted_scores
    )
    adjusted_probabilities = (
        adjusted_scores.outcome_probabilities() if shift is not None else prediction.probabilities
    )
    adjusted = {
        "parent_stage": "unadjusted",
        "score_generating": True,
        **score_stage(adjusted_scores, max_goals, adjusted_probabilities),
    }
    assistance = (
        market_assisted_probabilities(adjusted_probabilities, quote, market_pool)
        if quote is not None and market_pool is not None
        else None
    )
    market = (
        None
        if assistance is None
        else {
            "parent_stage": "personnel_adjusted",
            "score_generating": False,
            **assistance,
        }
    )
    return (
        {
            "unadjusted": unadjusted,
            "personnel_adjusted": adjusted,
            "market_assisted": market,
        },
        adjusted_scores,
        adjusted_probabilities,
        assistance,
    )


def weekly_window(observed_at: datetime, horizon_days: int) -> tuple[datetime, datetime]:
    """The impact slate: the London day of the observation, then the next horizon days.

    The window starts at midnight in Europe/London so that a refresh during a matchday
    keeps the fixtures that already finished on that day. It ends at the horizon, which
    the observation time measures, so the slate is the same for every division.
    """
    day = observed_at.astimezone(LONDON).date()
    start = datetime.combine(day, time.min, tzinfo=LONDON).astimezone(UTC)
    return start, observed_at + timedelta(days=horizon_days)


def started_slate(live: LiveSeason, window_start: datetime) -> list[dict]:
    """Fixtures of the current London day that started, with the result when there is one."""
    started = []
    for row in live.details.values():
        if row["status"] not in ("finished", *STARTED_WITHOUT_RESULT) or not row["kickoff_time"]:
            continue
        kickoff = timestamp(row["kickoff_time"])
        if not window_start <= kickoff <= live.observed_at:
            continue
        home, away = row["home_goals"], row["away_goals"]
        settled = row["status"] == "finished" and home is not None and away is not None
        started.append(
            {
                "match_id": row["match_id"],
                "home_team_id": row["home_team_id"],
                "away_team_id": row["away_team_id"],
                "kickoff_time": row["kickoff_time"],
                "match_date": row["match_date"],
                "status": row["status"],
                "outcome": ("H" if home > away else "A" if away > home else "D")
                if settled
                else None,
            }
        )
    started.sort(key=lambda row: (row["kickoff_time"], row["match_id"]))
    return started


def check_freshness(live: LiveSeason, max_age_hours: float) -> None:
    if not math.isfinite(max_age_hours) or max_age_hours <= 0:
        raise ValueError("Maximum snapshot age must be positive and finite")
    now = datetime.now(UTC)
    if live.observed_at > now:
        raise ValueError("Snapshot observation time is in the future")
    observed = timestamp(live.manifest["fixtures_retrieved_at"])
    age = (now - observed).total_seconds() / 3600
    if age > max_age_hours:
        raise ValueError(f"Fixture data is {age:.1f} hours old; collect fresh data")


def current_table(live: LiveSeason, adjustments: list[dict]) -> dict[str, dict]:
    table = {team: {"played": 0, "current_points": 0} for team in live.teams}
    for match in live.played:
        home, away = table[match.fixture.home_team_id], table[match.fixture.away_team_id]
        home["played"] += 1
        away["played"] += 1
        home["current_points"] += 3 if match.outcome == "H" else int(match.outcome == "D")
        away["current_points"] += 3 if match.outcome == "A" else int(match.outcome == "D")
    for adjustment in adjustments:
        table[adjustment["team_id"]]["current_points"] += adjustment["points"]
    return table


def build_forecast(
    live: LiveSeason,
    model: ForecastModel,
    training: list[Match],
    run: dict,
    simulations: int,
    seed: int,
    max_goals: int,
    adjustments: list[dict],
    europe: EuropeScenario | None = None,
    market_quotes: list[dict] | None = None,
    market_pool: dict | None = None,
    impact_horizon_days: int = 7,
    personnel: dict | None = None,
) -> dict:
    personnel = personnel or {}
    shifts = {
        match_id: record["home_log_rate_shift"]
        for match_id, record in personnel.items()
        if record["home_log_rate_shift"] is not None
    }
    # A match that started without a result is simulated as a match that is not played, so one
    # unsettled result no longer stops the projection of a whole division.
    unsettled_details = [
        {
            "match_id": row["match_id"],
            "home_team_id": row["home_team_id"],
            "away_team_id": row["away_team_id"],
            "match_date": row["match_date"],
            "kickoff_time": row["kickoff_time"],
            "status": row["status"],
        }
        for row in live.details.values()
        if row["status"] in STARTED_WITHOUT_RESULT
    ]
    unsettled = [row["match_id"] for row in unsettled_details]
    unscheduled = [
        row["match_id"] for row in live.details.values() if row["status"] == "unscheduled"
    ]
    window_start, window_end = weekly_window(live.observed_at, impact_horizon_days)
    window = {
        "horizon_days": impact_horizon_days,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "started": started_slate(live, window_start),
    }
    impact_fixtures = {
        row["match_id"]
        for row in live.details.values()
        if row["status"] == "scheduled"
        and row["kickoff_time"]
        and live.observed_at < timestamp(row["kickoff_time"]) <= window_end
    }
    simulation = simulate_season(
        model,
        live.played,
        live.remaining,
        list(live.teams),
        model.as_of,
        simulations,
        seed,
        adjustments,
        europe,
        results_observed_at=live.observed_at,
        impact_fixtures=impact_fixtures,
        impact_horizon_days=impact_horizon_days,
        impact_window=(window_start, window_end),
        log_rate_shifts=shifts,
    )
    table = current_table(live, adjustments)
    for row in simulation["teams"]:
        row.update(table[row["team_id"]])
    if unscheduled:
        simulation["assumptions"].append(UNSCHEDULED_PLACEHOLDER)
    if unsettled:
        simulation["assumptions"].append(UNSETTLED_PLACEHOLDER)
    matches = []
    market_quotes = market_quotes or []
    selected_quotes = {}
    if market_pool:
        for quote in market_quotes:
            if quote["family"] != market_pool["market_family"]:
                continue
            if quote["match_id"] in selected_quotes:
                raise ValueError(f"Duplicate current market quote: {quote['match_id']}")
            selected_quotes[quote["match_id"]] = quote
    for fixture in live.remaining:
        # A match in play gets no published match forecast; its pre-match numbers are stale.
        if fixture.match_id in unsettled:
            continue
        prediction = model.predict_match(fixture)
        stages, scores, probabilities, assistance = forecast_probability_stages(
            prediction,
            max_goals,
            shifts.get(fixture.match_id),
            selected_quotes.get(fixture.match_id),
            market_pool,
        )
        structural = {
            "p_home": float(probabilities[0]),
            "p_draw": float(probabilities[1]),
            "p_away": float(probabilities[2]),
        }
        matches.append(
            {
                **live.details[fixture.match_id],
                "model_forecast_date": str(fixture.match_date),
                **structural,
                "structural_probabilities": structural,
                "market_assisted_probabilities": assistance,
                "market_assisted_p_home": None if assistance is None else assistance["p_home"],
                "market_assisted_p_draw": None if assistance is None else assistance["p_draw"],
                "market_assisted_p_away": None if assistance is None else assistance["p_away"],
                "primary_probability_source": "structural",
                "primary_p_home": structural["p_home"],
                "primary_p_draw": structural["p_draw"],
                "primary_p_away": structural["p_away"],
                "stages": stages,
                "personnel": personnel.get(fixture.match_id),
                "score_distribution": stages["personnel_adjusted"]["score_distribution"],
            }
        )
    matches.sort(key=lambda row: (row["kickoff_time"] or "9999", row["match_id"]))
    generated = datetime.now(UTC)
    seen = set()
    for row in matches:
        eligible = row["kickoff_time"] and timestamp(row["kickoff_time"]) > generated
        next_for = (
            [team for team in (row["home_team_id"], row["away_team_id"]) if team not in seen]
            if eligible
            else []
        )
        row["next_match_for_teams"] = next_for
        seen.update(next_for)
    strengths = []
    for team in live.teams:
        index = model.team_index.get(team)
        state = (
            model.team_summary(team, live.season_id)
            if hasattr(model, "team_summary")
            else {
                "team_id": team,
                "attack_log_rate": float(model.attack[index]) if index is not None else 0.0,
                "defense_log_rate": float(model.defense[index]) if index is not None else 0.0,
            }
        )
        attack, defense = state["attack_log_rate"], state["defense_log_rate"]
        strengths.append(
            {
                **state,
                "attack_multiplier": math.exp(attack),
                "defense_multiplier": math.exp(defense),
                "training_matches": sum(
                    team in (m.fixture.home_team_id, m.fixture.away_team_id) for m in training
                ),
            }
        )
    forecast = {
        "schema_version": 2,
        "season_id": live.season_id,
        "generated_at": generated.isoformat(),
        "state_observed_at": live.observed_at.isoformat(),
        "model_results_cutoff": str(model.as_of),
        "model": run["model"],
        "state_uncertainty": "posterior" if hasattr(model, "sample_forecast_state") else "fixed",
        "future_state_evolution": bool(getattr(model, "fit_diagnostics", {}).get("future_states")),
        "fit_diagnostics": getattr(model, "fit_diagnostics", {}),
        "training_matches": len(training),
        "training_date_max": str(max(m.fixture.match_date for m in training)),
        "league_away_goal_rate": math.exp(float(model.intercept)),
        "home_scoring_multiplier": math.exp(float(model.home_advantage)),
        "team_names": live.teams,
        "team_strengths": strengths,
        "matches": matches,
        "personnel": {
            "kappa": KAPPA,
            "horizon_days": HORIZON.days,
            "competitions": list(COMPETITIONS),
            "records": len(personnel),
            "adjusted_fixtures": len(shifts),
            "persistent_state_changed": False,
        },
        "market_assistance": None
        if market_pool is None
        else {
            **market_pool,
            "available_match_forecasts": sum(
                row["market_assisted_probabilities"] is not None for row in matches
            ),
            "season_simulation_uses_market": False,
        },
        "simulation": simulation,
        "impact_window": window,
        "simulation_unavailable_reason": None,
        "fixtures_awaiting_results": unsettled,
        "unsettled_fixtures": unsettled_details,
        "unsettled_placeholder": UNSETTLED_PLACEHOLDER if unsettled else None,
        "unscheduled_fixtures": unscheduled,
        "unscheduled_placeholder": UNSCHEDULED_PLACEHOLDER if unscheduled else None,
        "results_crosschecked": live.results_crosschecked,
        "competition_id": live.competition_id,
        "competition_name": competition(live.competition_id).name,
        "sources": live.manifest["files"],
        "source_errors": live.manifest["errors"],
    }
    return forecast
