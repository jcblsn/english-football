"""Reference frame of the Quality level: the common direction of the division clubs.

The match likelihood sees only differences of Quality. At each preseason and midseason cutoff, this
script fits one observation-noise member of M10 and of M7 in each division and measures the posterior
of the mean Quality of the clubs that continue into the season. It then forecasts the first ten
matches of each entrant against a continuing club from the preseason state, as the filter does and
with the entrant referenced to the mean Quality of all clubs of the season.

Usage: uv run --with pandas --with pyarrow python scripts/research/m10_frame.py --output runs/m10-frame
"""

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from epl_forecast.competitions import COMPETITION_IDS
from epl_forecast.datasets import Dataset
from epl_forecast.models.poisson import PoissonMixture
from epl_forecast.storage import load_environment
from epl_forecast.training import training_matches

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m10_premerge_rolling import config_for  # noqa: E402
from m10_variants import CANDIDATES  # noqa: E402

from epl_forecast.models.xg_quality_tilt import XGQualityTiltFilter  # noqa: E402


def member(name, observations, competition):
    """One observation-noise member, chance probability 0.2, of the candidate."""
    model = XGQualityTiltFilter(observations, 0.2, **CANDIDATES[name]["dynamics"])
    model.primary_competition = competition
    return model


def club_slots(model, team):
    start = model._team_slice(team).start
    return start, start + model.team_dimensions - 1


def quality_vector(model, teams, size):
    vector = np.zeros(size)
    for team in teams:
        level, form = club_slots(model, team)
        vector[level] += 1 / len(teams)
        if model.team_dimensions == 3:
            vector[form] += 1 / len(teams)
    return vector


def unit(model, team, size):
    vector = np.zeros(size)
    level, form = club_slots(model, team)
    vector[level] = 1
    if model.team_dimensions == 3:
        vector[form] = 1
    return vector


def analyse(competition, name, matches, observations, output_rows, forecast_rows):
    config, spec = config_for(competition, name, observations)
    model = member(name, observations, competition)
    history = sorted(
        (m for m in matches if m.fixture.competition_id == competition),
        key=lambda m: (m.fixture.match_date, m.fixture.match_id),
    )
    seasons = sorted({m.fixture.season_id for m in history})
    for season in seasons:
        rows = [m for m in history if m.fixture.season_id == season]
        first = rows[0].fixture.match_date
        cutoffs = [("preseason", first - timedelta(days=1))]
        middle = date(first.year + 1, 1, 1)
        if rows[-1].fixture.match_date > middle:
            cutoffs.append(("midseason", middle))
        for phase, cutoff in cutoffs:
            try:
                training = training_matches(matches, config, spec, cutoff)
            except ValueError:
                continue
            model.fit(training, cutoff)
            mean, covariance = model.population_moments()
            size = len(mean)
            clubs = sorted({t for m in rows for t in (m.fixture.home_team_id, m.fixture.away_team_id)})
            fitted = [c for c in clubs if model._uses_fitted_state(c, season)]
            if phase == "midseason":
                fitted = [c for c in fitted if model._last_season.get(c) == season]
            entrants = [c for c in clubs if c not in fitted]
            if len(fitted) < 2:
                continue
            common = quality_vector(model, fitted, size)
            common_variance = common @ covariance @ common
            own, relative = [], []
            for team in fitted:
                vector = unit(model, team, size)
                own.append(vector @ covariance @ vector)
                relative.append((vector - common) @ covariance @ (vector - common))
            loading = np.array([1, 0, 1][: model.team_dimensions])
            entry_means = (
                [float(loading @ model.team_state(t, season).mean) for t in entrants]
                if phase == "preseason"
                else []
            )
            # The entry labels are relative to the mean of every club of the season, entrants included.
            offset = float(common @ mean) + sum(entry_means) / len(fitted)
            entry_variance = [
                np.array([1, 0, 1][: model.team_dimensions])
                @ model.team_state(team, season).covariance
                @ np.array([1, 0, 1][: model.team_dimensions])
                for team in entrants
            ] if phase == "preseason" else []
            output_rows.append(
                {
                    "competition_id": competition,
                    "candidate": name,
                    "season_id": season,
                    "phase": phase,
                    "cutoff": str(cutoff),
                    "state_clubs": len(model.team_index),
                    "continuing_clubs": len(fitted),
                    "entrants": len(entrants),
                    "common_mean": float(common @ mean),
                    "common_sd": float(np.sqrt(common_variance)),
                    "entry_mean": float(np.mean(entry_means)) if entry_means else None,
                    "reference_offset": offset,
                    "club_quality_variance": float(np.mean(own)),
                    "club_relative_variance": float(np.mean(relative)),
                    "frame_variance": float(np.mean(own) - np.mean(relative)),
                    "entrant_quality_variance": float(np.mean(entry_variance))
                    if entry_variance
                    else None,
                }
            )
            if phase != "preseason" or not entrants:
                continue
            counts = dict.fromkeys(entrants, 0)
            for match in rows:
                fixture = match.fixture
                home, away = fixture.home_team_id, fixture.away_team_id
                pair = [t for t in (home, away) if t in counts]
                if len(pair) != 1 or counts[pair[0]] >= 10:
                    continue
                entrant = pair[0]
                opponent = away if entrant == home else home
                counts[entrant] += 1
                log_mean, log_covariance = model.forecast_moments(fixture)
                vector = unit(model, opponent, size)
                frame = vector @ covariance @ vector - (vector - common) @ covariance @ (
                    vector - common
                )
                sign = 1.0 if entrant == home else -1.0
                shift = sign * offset * np.array([1.0, -1.0])
                loading = np.array([[1.0, -1.0], [-1.0, 1.0]])
                variants = {
                    "filter": (log_mean, log_covariance),
                    "referenced": (log_mean + shift, log_covariance - frame * loading),
                }
                result = {
                    "competition_id": competition,
                    "candidate": name,
                    "season_id": season,
                    "match_id": fixture.match_id,
                    "entrant": entrant,
                    "entrant_home": entrant == home,
                    "entrant_match": counts[entrant],
                    "outcome": match.outcome,
                    "home_goals": match.home_goals,
                    "away_goals": match.away_goals,
                    "frame_variance": float(frame),
                    "frame_shift": offset,
                }
                for label, (m, c) in variants.items():
                    scores = PoissonMixture(m, c, model.quadrature_order)
                    p = scores.outcome_probabilities()
                    result[f"{label}_p_home"], result[f"{label}_p_draw"], result[f"{label}_p_away"] = p
                    result[f"{label}_score_log_probability"] = scores.log_probability(
                        match.home_goals, match.away_goals
                    )
                forecast_rows.append(result)
        print(competition, name, season, flush=True)


def report(output, tables):
    frames = pd.concat(pd.read_parquet(p) for p in sorted(output.glob("*-frame.parquet")))
    frames = frames[frames.season_id >= "2012-2013"]
    columns = [
        "common_mean",
        "common_sd",
        "reference_offset",
        "club_quality_variance",
        "frame_variance",
        "entrant_quality_variance",
    ]
    summary = frames.groupby(["competition_id", "candidate", "phase"])[columns].mean()
    latest = frames[frames.season_id == frames.season_id.max()].set_index(
        ["competition_id", "candidate", "phase"]
    )[["common_sd", "reference_offset"]]
    summary = summary.join(latest, rsuffix="_2026_27").reset_index()
    entrants = pd.concat(pd.read_parquet(p) for p in sorted(output.glob("*-entrants.parquet")))
    entrants = entrants[entrants.season_id.between("2015-2016", "2025-2026")]
    for label in ("filter", "referenced"):
        p = np.select(
            [entrants.outcome == "H", entrants.outcome == "D"],
            [entrants[f"{label}_p_home"], entrants[f"{label}_p_draw"]],
            entrants[f"{label}_p_away"],
        )
        entrants[f"{label}_log_loss"] = -np.log(p)
    entrants["log_loss"] = entrants.referenced_log_loss - entrants.filter_log_loss
    entrants["score_nll"] = (
        entrants.filter_score_log_probability - entrants.referenced_score_log_probability
    )
    entrants["entrant_win_change"] = np.where(
        entrants.entrant_home,
        entrants.referenced_p_home - entrants.filter_p_home,
        entrants.referenced_p_away - entrants.filter_p_away,
    )
    entrants["matches"] = np.where(entrants.entrant_match <= 5, "1-5", "6-10")
    referenced = (
        entrants.groupby(["competition_id", "candidate", "matches"])
        .agg(
            count=("log_loss", "size"),
            referenced_minus_filter_log_loss=("log_loss", "mean"),
            referenced_minus_filter_score_nll=("score_nll", "mean"),
            mean_entrant_win_change=("entrant_win_change", "mean"),
            mean_absolute_entrant_win_change=("entrant_win_change", lambda x: x.abs().mean()),
        )
        .reset_index()
    )
    tables.mkdir(parents=True, exist_ok=True)
    summary.to_csv(tables / "frame_summary.csv", index=False, float_format="%.5f")
    referenced.to_csv(tables / "frame_entrants.csv", index=False, float_format="%.5f")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tables", type=Path)
    parser.add_argument("--competitions", nargs="+", default=COMPETITION_IDS)
    parser.add_argument("--candidates", nargs="+", default=["M10", "M7"])
    args = parser.parse_args()
    if args.tables:
        report(args.output, args.tables)
        return
    load_environment()
    data = Dataset()
    try:
        matches, observations = data.matches(), data.xg_observations()
    finally:
        data.close()
    args.output.mkdir(parents=True, exist_ok=True)
    for competition in args.competitions:
        for name in args.candidates:
            rows, forecasts = [], []
            analyse(competition, name, matches, observations, rows, forecasts)
            pd.DataFrame(rows).to_parquet(args.output / f"{competition}-{name}-frame.parquet")
            pd.DataFrame(forecasts).to_parquet(args.output / f"{competition}-{name}-entrants.parquet")


if __name__ == "__main__":
    main()
