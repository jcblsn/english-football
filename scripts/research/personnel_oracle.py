"""Phase 1 oracle: does realized personnel discontinuity make M7 overconfident?

Frozen M7 makes each pre-match forecast with results before the match day only.
Realized continuity uses the actual target minutes, so it is an oracle input and
never a forecast input.
"""

import argparse
import copy
import json
from collections import defaultdict
from datetime import date
from itertools import groupby
from pathlib import Path

import numpy as np

from epl_forecast.artifacts import execution_provenance, new_run_directory
from epl_forecast.cli import load_config, save_rows
from epl_forecast.datasets import Dataset
from epl_forecast.models import make_model
from epl_forecast.storage import load_environment, write_json
from epl_forecast.training import training_matches

WINDOW = 8
REFERENCE_MINUTES = 90
FULL_LINEUP_MINUTES = 700
MAX_GOALS = 15
SEED = 20260915
COMPETITIONS = ("eng-premier-league", "eng-championship")


def lineups(rows):
    minutes = defaultdict(dict)
    for row in rows:
        players = minutes[row["match_id"], row["team_id"]]
        players[row["player_id"]] = players.get(row["player_id"], 0) + min(
            int(row["minutes"]), REFERENCE_MINUTES
        )
    return minutes


def continuity(matches, minutes, window=WINDOW):
    """Continuity loss D for each (match, team); None when a lineup is missing or incomplete."""
    by_team = defaultdict(list)
    for match in sorted(matches, key=lambda m: (m.fixture.match_date, m.fixture.match_id)):
        for team in (match.fixture.home_team_id, match.fixture.away_team_id):
            by_team[team].append(match)
    complete = {
        key: players
        for key, players in minutes.items()
        if sum(players.values()) >= FULL_LINEUP_MINUTES
    }
    result = {}
    for team, games in by_team.items():
        for index, match in enumerate(games):
            target = complete.get((match.fixture.match_id, team))
            previous = [
                g for g in games[:index] if g.fixture.match_date < match.fixture.match_date
            ][-window:]
            recent = [complete.get((g.fixture.match_id, team)) for g in previous]
            if target is None or len(recent) < window or any(r is None for r in recent):
                result[match.fixture.match_id, team] = None
                continue
            weights = defaultdict(float)
            for players in recent:
                for player, value in players.items():
                    weights[player] += value
            total = sum(weights.values())
            retained = sum(
                weight * target.get(player, 0) / REFERENCE_MINUTES
                for player, weight in weights.items()
            )
            result[match.fixture.match_id, team] = 1 - retained / total
    return result


def api_xg(data):
    return {
        (r["match_id"], r["team_id"]): float(r["expected_goals"])
        for r in data.rows(
            "SELECT match_id, team_id, expected_goals FROM team_statistics "
            "WHERE expected_goals IS NOT NULL"
        )
    }


def understat_xg(observations):
    values = {}
    for row in observations:
        values[row["match_id"], row["home_team_id"]] = float(row["home_xg"])
        values[row["match_id"], row["away_team_id"]] = float(row["away_xg"])
    return values


def predictive_rows(matches, config, spec, start, end, discontinuity, xg, rng):
    competition = config["competition_id"]
    targets = sorted(
        (
            m
            for m in matches
            if m.fixture.competition_id == competition and start <= m.fixture.match_date < end
        ),
        key=lambda m: (m.fixture.match_date, m.fixture.match_id),
    )
    model, rows = make_model(spec), []
    previous_season = None
    for day, games in groupby(targets, key=lambda m: m.fixture.match_date):
        games = list(games)
        if games[0].fixture.season_id != previous_season:
            previous_season = games[0].fixture.season_id
            print(f"{competition} {previous_season}", flush=True)
        model.fit(training_matches(matches, config, spec, day), as_of=day)
        for match in games:
            f = match.fixture
            scores = model.predict_match(f).scores
            grid, _ = scores.grid(MAX_GOALS)
            grid = grid / grid.sum()
            probabilities = np.array(scores.outcome_probabilities())
            outcome = np.zeros(3)
            outcome["HDA".index(match.outcome)] = 1
            match_row = {
                "competition_id": competition,
                "season_id": f.season_id,
                "match_id": f.match_id,
                "match_date": str(day),
                "score_nll": -scores.log_probability(match.home_goals, match.away_goals),
                "hda_abs_error": float(np.abs(probabilities - outcome).sum()),
                "hda_log_loss": float(-np.log(probabilities @ outcome)),
                "brier": float(np.sum((probabilities - outcome) ** 2)),
            }
            goals = (match.home_goals, match.away_goals)
            teams = (f.home_team_id, f.away_team_id)
            for side, pmf in enumerate((grid.sum(1), grid.sum(0))):
                support = np.arange(len(pmf))
                mean = float(pmf @ support)
                variance = float(pmf @ (support - mean) ** 2)
                g = goals[side]
                cdf_below = float(pmf[:g].sum())
                pit = cdf_below + rng.uniform() * float(pmf[g])
                proxy = xg.get((f.match_id, teams[side]))
                log_mean = float(scores.log_mean[side])
                log_variance = float(scores.log_covariance[side, side])
                rows.append(
                    {
                        **match_row,
                        "side": ("home", "away")[side],
                        "team_id": teams[side],
                        "opponent_id": teams[1 - side],
                        "goals": g,
                        "predictive_mean": mean,
                        "predictive_variance": variance,
                        "residual": g - mean,
                        "z2": (g - mean) ** 2 / variance,
                        "goal_nll": float(-np.log(pmf[g])),
                        "pit": pit,
                        "covered_80": 0.1 <= pit <= 0.9,
                        "log_rate_mean": log_mean,
                        "log_rate_variance": log_variance,
                        "xg": proxy,
                        "log_xg_z2": None
                        if not proxy
                        else (np.log(proxy) - log_mean) ** 2 / log_variance,
                        "d_own": discontinuity.get((f.match_id, teams[side])),
                        "d_opponent": discontinuity.get((f.match_id, teams[1 - side])),
                    }
                )
    return rows


def cluster_slopes(rows, outcome, samples, rng):
    """OLS of an outcome on continuity loss of both teams, with whole-season resampling."""
    clusters = defaultdict(lambda: [np.zeros((3, 3)), np.zeros(3), 0])
    for row in rows:
        value = row[outcome]
        if value is None or row["d_own"] is None or row["d_opponent"] is None:
            continue
        x = np.array([1.0, row["d_own"], row["d_opponent"]])
        cluster = clusters[row["competition_id"], row["season_id"]]
        cluster[0] += np.outer(x, x)
        cluster[1] += x * float(value)
        cluster[2] += 1
    keys = sorted(clusters)
    xtx = np.array([clusters[k][0] for k in keys])
    xty = np.array([clusters[k][1] for k in keys])
    estimate = np.linalg.solve(xtx.sum(0), xty.sum(0))
    draws = []
    for _ in range(samples):
        pick = rng.integers(0, len(keys), len(keys))
        draws.append(np.linalg.solve(xtx[pick].sum(0), xty[pick].sum(0)))
    draws = np.array(draws)
    per_season = [
        {
            "cluster": "/".join(k),
            "n": clusters[k][2],
            "slope_own": float(np.linalg.lstsq(clusters[k][0], clusters[k][1], rcond=None)[0][1]),
        }
        for k in keys
    ]
    return {
        "outcome": outcome,
        "n": int(sum(clusters[k][2] for k in keys)),
        "clusters": len(keys),
        "intercept": float(estimate[0]),
        "slope_own": float(estimate[1]),
        "slope_own_interval": np.quantile(draws[:, 1], [0.025, 0.975]).tolist(),
        "slope_opponent": float(estimate[2]),
        "slope_opponent_interval": np.quantile(draws[:, 2], [0.025, 0.975]).tolist(),
        "seasons_with_positive_own_slope": sum(r["slope_own"] > 0 for r in per_season),
        "per_season": per_season,
    }


def deciles(rows):
    usable = [r for r in rows if r["d_own"] is not None]
    edges = np.quantile([r["d_own"] for r in usable], np.linspace(0, 1, 11))
    result = []
    for index in range(10):
        low, high = edges[index], edges[index + 1]
        selected = [
            r for r in usable if low <= r["d_own"] < high or (index == 9 and r["d_own"] == high)
        ]
        result.append(
            {
                "decile": index + 1,
                "d_low": float(low),
                "d_high": float(high),
                "team_matches": len(selected),
                "mean_z2": float(np.mean([r["z2"] for r in selected])),
                "mean_goal_nll": float(np.mean([r["goal_nll"] for r in selected])),
                "coverage_80": float(np.mean([r["covered_80"] for r in selected])),
                "mean_residual": float(np.mean([r["residual"] for r in selected])),
                "mean_predictive_variance": float(
                    np.mean([r["predictive_variance"] for r in selected])
                ),
            }
        )
    return result


def analyze(rows, samples):
    rng = np.random.default_rng(SEED)
    for row in rows:
        row["uncovered_80"] = None if row["covered_80"] is None else float(not row["covered_80"])
    outcomes = ("z2", "goal_nll", "uncovered_80", "residual", "log_xg_z2")
    summary = {"pooled": [cluster_slopes(rows, o, samples, rng) for o in outcomes]}
    for competition in COMPETITIONS:
        selected = [r for r in rows if r["competition_id"] == competition]
        if selected:
            summary[competition] = [cluster_slopes(selected, o, samples, rng) for o in outcomes]
    matches = {}
    for row in rows:
        entry = matches.setdefault(row["match_id"], {**row, "d_own": 0.0, "d_opponent": 0.0})
        if row["d_own"] is None:
            entry["missing"] = True
        else:
            entry["d_own" if row["side"] == "home" else "d_opponent"] = row["d_own"]
    match_rows = [r for r in matches.values() if not r.get("missing")]
    summary["match_level"] = [
        cluster_slopes(match_rows, o, samples, rng)
        for o in ("score_nll", "hda_abs_error", "hda_log_loss")
    ]
    return summary


def main():
    load_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2017, 8, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 7, 1))
    parser.add_argument("--competitions", nargs="+", default=list(COMPETITIONS))
    parser.add_argument("--bootstrap", type=int, default=2000)
    args = parser.parse_args()
    new_run_directory(args.output)
    data = Dataset(args.data)
    try:
        matches = data.matches()
        minutes = lineups(data.player_history())
        understat = understat_xg(data.process())
        api = api_xg(data)
        provenance = data.provenance()
    finally:
        data.close()
    discontinuity = continuity(matches, minutes)
    rng = np.random.default_rng(SEED)
    rows = []
    for competition in args.competitions:
        config = load_config(Path("configs/product.toml"))
        config["competition_id"] = competition
        spec = copy.deepcopy(next(s for s in config["models"] if s["id"] == "M7-xg-v1"))
        spec["parameters"].update(competition_id=competition, data_root=str(args.data))
        config["models"] = [spec]
        xg = understat if competition == "eng-premier-league" else api
        rows.extend(
            predictive_rows(matches, config, spec, args.start, args.end, discontinuity, xg, rng)
        )
    save_rows(args.output / "team_matches.csv", rows)
    summary = analyze(rows, args.bootstrap)
    write_json(args.output / "summary.json", summary)
    save_rows(args.output / "deciles.csv", deciles(rows))
    write_json(
        args.output / "manifest.json",
        {
            "execution": execution_provenance(),
            "window": WINDOW,
            "full_lineup_minutes": FULL_LINEUP_MINUTES,
            "reference_minutes": REFERENCE_MINUTES,
            "start": str(args.start),
            "end": str(args.end),
            "competitions": args.competitions,
            "team_matches": len(rows),
            "team_matches_with_continuity": sum(r["d_own"] is not None for r in rows),
            "data_manifest_batches": len(provenance["batches"]),
            "information": "M7 uses results before the match day; target minutes are an oracle",
        },
    )
    print(json.dumps({k: v for k, v in summary.items() if k == "pooled"}, indent=1)[:4000])


if __name__ == "__main__":
    main()
