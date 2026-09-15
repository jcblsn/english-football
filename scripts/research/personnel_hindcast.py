"""History-only chronological hindcast of matchday-squad continuity.

The hindcast estimates D_squad before each historical match day from information that history
itself dates: preceding matches and minutes, preceding matchday squads, and dated transfers or
matchday squads of another club. It uses no injury records, no squad captures and no FPL data.
Propensity tables and coefficients for a target season come from earlier seasons only.
"""

import argparse
import csv
import importlib.util
from collections import defaultdict
from pathlib import Path

import numpy as np

from epl_forecast.artifacts import execution_provenance, new_run_directory
from epl_forecast.cli import save_rows
from epl_forecast.datasets import Dataset
from epl_forecast.live import LONDON
from epl_forecast.research.personnel_mean import (
    FULL_RECENT_MINUTES,
    FULL_STARTING_MINUTES,
    WINDOW,
    lineup_minutes,
    shifted_scores,
)
from epl_forecast.research.roster import BENCHED, CLASSES, RosterEvidence, first
from epl_forecast.storage import load_environment, write_json

_spec = importlib.util.spec_from_file_location(
    "personnel_transition_script", Path(__file__).with_name("personnel_transition.py")
)
transition = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(transition)
pm = transition.pm

COMPETITIONS = ("eng-premier-league", "eng-championship")
LAST_SEASON = "2025-2026"
ARMS = ("oracle", "hindcast", "refit")
METRICS = ("hda_log_loss", "brier", "score_nll", "team_goal_nll")
SEED = 20260918


def departed_before(evidence, player, team, target):
    """Dated evidence strictly before the match day that the player left the club."""
    since = evidence.last_for(player, team, target)
    if since is None:
        return False
    events = [
        (day, source == team, destination == team)
        for day, source, destination in evidence.transfers.get(player, ())
        if since < day < target and team in (source, destination)
    ]
    events.extend(
        (day, True, False)
        for day, other, _ in evidence._spells_between(player, since, target)
        if other != team
    )
    left = False
    for _, out, back in sorted(events, key=first):
        left = (left or out) and not back
    return left


def features_command(args):
    new_run_directory(args.output)
    data = Dataset(args.data)
    try:
        matches = data.matches()
        played = data.player_history()
        squads = data.rows(
            "SELECT match_id, team_id, player_id, season_id, competition_id, kickoff_time, starts "
            "FROM appearances WHERE player_id IS NOT NULL"
        )
        transfers = data.rows(
            "SELECT player_id, transfer_date, from_team_id, to_team_id FROM transfers"
        )
        names = {
            row["player_id"]: row["name"]
            for row in data.rows("SELECT player_id, name FROM players")
        }
        provenance = data.provenance()
    finally:
        data.close()
    days = {match.fixture.match_id: match.fixture.match_date for match in matches}
    dated = []
    for row in squads:
        day = days.get(row["match_id"])
        if day is None and row["kickoff_time"] is not None:
            day = row["kickoff_time"].astimezone(LONDON).date()
        if day is not None:
            dated.append({**row, "match_date": day})
    evidence = RosterEvidence(dated, transfers)
    matchday = defaultdict(set)
    starters_seen = defaultdict(set)
    for row in dated:
        matchday[row["match_id"], row["team_id"]].add(row["player_id"])
        if row["starts"]:
            starters_seen[row["match_id"], row["team_id"]].add(row["player_id"])
    recent = lineup_minutes(played)
    target_starts = lineup_minutes(played, starters=True)
    by_team = defaultdict(list)
    for match in sorted(matches, key=lambda item: (item.fixture.match_date, item.fixture.match_id)):
        for team in (match.fixture.home_team_id, match.fixture.away_team_id):
            by_team[team].append(match)
    player_rows, team_rows = [], []
    for team, games in by_team.items():
        for index, match in enumerate(games):
            fixture = match.fixture
            if fixture.competition_id not in COMPETITIONS or fixture.season_id > LAST_SEASON:
                continue
            previous = [g for g in games[:index] if g.fixture.match_date < fixture.match_date]
            previous = previous[-WINDOW:]
            histories = [recent.get((g.fixture.match_id, team)) for g in previous]
            starters = target_starts.get((fixture.match_id, team))
            if (
                starters is None
                or sum(starters.values()) < FULL_STARTING_MINUTES
                or len(histories) < WINDOW
                or any(row is None or sum(row.values()) < FULL_RECENT_MINUTES for row in histories)
            ):
                continue
            weights = defaultdict(float)
            for players in histories:
                for player, minutes in players.items():
                    weights[player] += minutes
            window_squads = [matchday.get((g.fixture.match_id, team), set()) for g in previous]
            target_squad = matchday.get((fixture.match_id, team), set())
            key = {"match_id": fixture.match_id, "team_id": team}
            team_rows.append(
                {
                    **key,
                    "season_id": fixture.season_id,
                    "competition_id": fixture.competition_id,
                    "match_date": fixture.match_date,
                    "target_squad_size": len(target_squad),
                    "target_starters": len(starters_seen.get((fixture.match_id, team), set())),
                    "minimum_window_squad_size": min(len(row) for row in window_squads),
                    "window_seasons": len({g.fixture.season_id for g in previous}),
                    "window_competitions": len({g.fixture.competition_id for g in previous}),
                }
            )
            for player, weight in weights.items():
                player_rows.append(
                    {
                        **key,
                        "season_id": fixture.season_id,
                        "player_id": player,
                        "player_name": names.get(player),
                        "weight": weight,
                        "squads": sum(player in row for row in window_squads),
                        "in_last_squad": player in window_squads[-1],
                        "departed": departed_before(evidence, player, team, fixture.match_date),
                        "in_target_squad": player in target_squad,
                    }
                )
    save_rows(args.output / "players.csv", player_rows)
    save_rows(args.output / "teams.csv", team_rows)
    write_json(
        args.output / "manifest.json",
        {
            "execution": execution_provenance(),
            "team_matches": len(team_rows),
            "player_rows": len(player_rows),
            "data_manifest_batches": len(provenance["batches"]),
            "information": "preceding matches, preceding matchday squads and dated departures "
            "before the match day; transfer rows were captured in September 2026 with "
            "provider dates",
        },
    )
    print(f"{len(team_rows)} team-matches, {len(player_rows)} player rows")


def load_players(path):
    players = defaultdict(list)
    with (path / "players.csv").open() as stream:
        for row in csv.DictReader(stream):
            players[row["match_id"], row["team_id"]].append(
                (
                    row["season_id"],
                    float(row["weight"]),
                    int(row["squads"]),
                    row["in_last_squad"] == "True",
                    row["departed"] == "True",
                    row["in_target_squad"] == "True",
                )
            )
    return players


def propensity(players, seasons):
    cells = defaultdict(lambda: [0, 0])
    for rows in players.values():
        for season, _, squads, last, departed, in_target in rows:
            if season in seasons and not departed:
                cell = cells[squads, last]
                cell[0] += 1
                cell[1] += in_target
    pooled = sum(hits for _, hits in cells.values()) / sum(count for count, _ in cells.values())
    return {key: hits / count for key, (count, hits) in cells.items()}, pooled


def expected(rows, table, pooled):
    total = sum(weight for _, weight, *_ in rows)
    represented = sum(
        weight * (0.0 if departed else table.get((squads, last), pooled))
        for _, weight, squads, last, departed, _ in rows
    )
    return 1 - represented / total


def realized(rows):
    total = sum(weight for _, weight, *_ in rows)
    return 1 - sum(weight for _, weight, *rest in rows if rest[-1]) / total


def statistics(estimates, labels):
    estimates, labels = np.asarray(estimates), np.asarray(labels)
    return {
        "n": int(len(estimates)),
        "bias": float(np.mean(estimates - labels)),
        "mean_absolute_error": float(np.mean(np.abs(estimates - labels))),
        "correlation": float(np.corrcoef(estimates, labels)[0, 1]),
    }


def report_command(args):
    new_run_directory(args.output)
    players = load_players(args.features)
    components = {}
    with (args.components / "components.csv").open() as stream:
        for row in csv.DictReader(stream):
            components[row["match_id"], row["team_id"]] = {
                k: float(row[k]) for k in ("d", *CLASSES)
            }
    rows = []
    for row in pm.load_forecasts(args.forecasts):
        if row["d_home"] is None or row["d_away"] is None:
            continue
        sides = [(row["match_id"], row[f"{side}_team_id"]) for side in ("home", "away")]
        if any(key not in players for key in sides):
            raise ValueError(f"Missing hindcast features for {row['match_id']}")
        for side, key in zip(("home", "away"), sides, strict=True):
            label = realized(players[key])
            oracle = components[key]["d"] - components[key][BENCHED]
            if abs(label - oracle) > 1e-9:
                raise ValueError(f"Realized D_squad does not recover {key}")
            row[f"squad_{side}"] = label
        row["opening_five"] = min(row["home_match_number"], row["away_match_number"]) <= 5
        rows.append(row)
    print(f"{len(rows)} matches", flush=True)
    table = np.array(
        [transition.likelihood_grid(r["_scores"], r["home_goals"], r["away_goals"]) for r in rows]
    )
    oracle_feature = np.array([[r["squad_away"] - r["squad_home"]] for r in rows])
    seasons = sorted({r["season_id"] for r in rows})
    all_seasons = sorted({season for values in players.values() for season, *_ in values})
    fits, scored, measurement = [], [], []
    for season in seasons[pm.INITIAL_SEASONS :]:
        earlier = {s for s in all_seasons if s < season}
        cells, pooled = propensity(players, earlier)
        estimates = {
            key: expected(values, cells, pooled)
            for key, values in players.items()
            if values[0][0] <= season
        }
        hindcast_feature = np.array(
            [
                [
                    estimates[r["match_id"], r["away_team_id"]]
                    - estimates[r["match_id"], r["home_team_id"]]
                ]
                for r in rows
            ]
        )
        training = np.array([r["season_id"] < season for r in rows])
        kappa_oracle = float(transition.fit(table[training], oracle_feature[training])[0])
        kappa_refit = float(transition.fit(table[training], hindcast_feature[training])[0])
        fits.append(
            {
                "target_season": season,
                "propensity_seasons": sorted(earlier),
                "propensity_cells": {f"{k[0]},{int(k[1])}": v for k, v in sorted(cells.items())},
                "kappa_oracle": kappa_oracle,
                "kappa_refit": kappa_refit,
            }
        )
        for index in np.flatnonzero(np.array([r["season_id"] == season for r in rows])):
            r = rows[index]
            control = pm.individual_scores(r, r["_scores"])
            deltas = {
                "oracle": kappa_oracle * oracle_feature[index, 0],
                "hindcast": kappa_oracle * hindcast_feature[index, 0],
                "refit": kappa_refit * hindcast_feature[index, 0],
            }
            result = {
                "match_id": r["match_id"],
                "competition_id": r["competition_id"],
                "season_id": season,
                "opening_five": r["opening_five"],
                "realized_difference": float(oracle_feature[index, 0]),
                "estimated_difference": float(hindcast_feature[index, 0]),
                **{f"control_{m}": control[m] for m in METRICS},
            }
            for arm, delta in deltas.items():
                scores = pm.individual_scores(
                    r, shifted_scores(r["_scores"], np.array([delta, -delta]))
                )
                result[f"{arm}_delta"] = float(delta)
                result.update({f"{arm}_{m}": scores[m] for m in METRICS})
            scored.append(result)
            for side in ("home", "away"):
                key = r["match_id"], r[f"{side}_team_id"]
                measurement.append(
                    {
                        "match_id": r["match_id"],
                        "team_id": key[1],
                        "season_id": season,
                        "competition_id": r["competition_id"],
                        "opening_five": r["opening_five"],
                        "estimate": estimates[key],
                        "realized": r[f"squad_{side}"],
                    }
                )
        print(f"{season}: kappa oracle {kappa_oracle:.4f}, refit {kappa_refit:.4f}", flush=True)

    def summarize(selected, label):
        result = {"scope": label, "matches": len(selected)}
        for m in METRICS:
            for arm in ARMS:
                result[f"{arm}_minus_control_{m}"] = float(
                    np.mean([x[f"{arm}_{m}"] - x[f"control_{m}"] for x in selected])
                )
        oracle_gain = result["oracle_minus_control_score_nll"]
        result["hindcast_share_of_oracle_score_nll"] = (
            None if oracle_gain == 0 else result["hindcast_minus_control_score_nll"] / oracle_gain
        )
        return result

    scopes = [("all", lambda x: True)]
    scopes += [(c, lambda x, c=c: x["competition_id"] == c) for c in COMPETITIONS]
    scopes += [("opening-five", lambda x: x["opening_five"])]
    scopes += [("after-opening-five", lambda x: not x["opening_five"])]
    for season in seasons[pm.INITIAL_SEASONS :]:
        scopes.append((season, lambda x, s=season: x["season_id"] == s))
    for low, high in ((0, 0.05), (0.05, 0.10), (0.10, 0.20), (0.20, 9)):
        scopes.append(
            (
                f"realized-squad-imbalance-{low:.2f}-{high:.2f}",
                lambda x, a=low, b=high: a <= abs(x["realized_difference"]) < b,
            )
        )
    summaries = [summarize([x for x in scored if select(x)], label) for label, select in scopes]

    clusters = defaultdict(list)
    for x in scored:
        clusters[x["competition_id"], x["season_id"]].append(x)
    keys = sorted(clusters)
    weights = np.array([len(clusters[k]) for k in keys])
    rng = np.random.default_rng(SEED)
    intervals = {}
    for left, right in (
        ("oracle", "control"),
        ("hindcast", "control"),
        ("refit", "control"),
        ("hindcast", "oracle"),
    ):
        name = f"{left}_minus_{right}"
        intervals[name] = {}
        for m in METRICS:
            values = np.array(
                [np.mean([x[f"{left}_{m}"] - x[f"{right}_{m}"] for x in clusters[k]]) for k in keys]
            )
            draws = []
            for _ in range(args.bootstrap):
                picked = rng.integers(0, len(keys), len(keys))
                draws.append(float(np.average(values[picked], weights=weights[picked])))
            intervals[name][m] = {
                "interval": np.quantile(draws, [0.025, 0.975]).tolist(),
                "clusters_below_zero": int(np.sum(values < 0)),
                "clusters": len(keys),
            }
    pairs = [(x["estimated_difference"], x["realized_difference"]) for x in scored]
    large = [(e, r) for e, r in pairs if abs(r) >= 0.10]
    measure = {
        "team_d": statistics(
            [x["estimate"] for x in measurement], [x["realized"] for x in measurement]
        ),
        "team_d_opening_five": statistics(
            [x["estimate"] for x in measurement if x["opening_five"]],
            [x["realized"] for x in measurement if x["opening_five"]],
        ),
        "away_minus_home_d": statistics([e for e, _ in pairs], [r for _, r in pairs]),
        "sign_agreement_realized_at_least_0.10": [
            int(sum(np.sign(e) == np.sign(r) for e, r in large)),
            len(large),
        ],
        "false_large_estimate": int(sum(abs(e) >= 0.10 and abs(r) < 0.05 for e, r in pairs)),
        "missed_large_realized": int(sum(abs(r) >= 0.10 and abs(e) < 0.05 for e, r in pairs)),
    }
    result = {
        "matches": len(rows),
        "fits": fits,
        "intervals": intervals,
        "measurement": measure,
    }
    save_rows(args.output / "chronological.csv", scored)
    save_rows(args.output / "measurement.csv", measurement)
    save_rows(args.output / "summary.csv", summaries)
    write_json(args.output / "result.json", result)
    write_json(
        args.output / "manifest.json",
        {
            "execution": execution_provenance(),
            "forecasts": str(args.forecasts),
            "features": str(args.features),
            "components": str(args.components),
            "bootstrap_samples": args.bootstrap,
            "arms": {
                "oracle": "realized D_squad with kappa fitted on earlier oracle seasons",
                "hindcast": "history-only expected D_squad with the same earlier-season oracle kappa",
                "refit": "history-only expected D_squad with kappa fitted on earlier-season expected D_squad",
            },
            "evidence_label": "retrospective chronological hindcast; D_squad was selected with these seasons",
        },
    )
    for row in summaries:
        print(row)
    print(result["intervals"], result["measurement"])


def main():
    load_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    features = commands.add_parser("features")
    features.add_argument("--data", type=Path, required=True)
    features.add_argument("--output", type=Path, required=True)
    features.set_defaults(func=features_command)
    report = commands.add_parser("report")
    report.add_argument("--forecasts", type=Path, required=True)
    report.add_argument("--features", type=Path, required=True)
    report.add_argument("--components", type=Path, required=True)
    report.add_argument("--output", type=Path, required=True)
    report.add_argument("--bootstrap", type=int, default=2000)
    report.set_defaults(func=report_command)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
