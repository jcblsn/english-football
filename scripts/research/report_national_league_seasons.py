"""Compare matched National League source and outside-fallback season panels."""

import argparse
import csv
import json
from pathlib import Path

import numpy as np

from epl_forecast.artifacts import execution_provenance, new_run_directory
from epl_forecast.cli import save_rows
from epl_forecast.datasets import Dataset
from epl_forecast.models.entry_prior import club_features
from epl_forecast.models.promotion import completed_seasons, season_strengths
from epl_forecast.storage import file_hash, load_environment, write_json

LEAGUE_TWO = "eng-league-two"
NATIONAL_LEAGUE = "eng-national-league"
METRICS = (
    "rank_rps",
    "points_crps",
    "coverage_50",
    "width_50",
    "coverage_80",
    "width_80",
    "coverage_90",
    "width_90",
    "rank_sd",
    "points_sd",
    "title_brier",
    "automatic_promotion_brier",
    "playoff_qualification_brier",
    "promotion_brier",
    "relegation_brier",
)
EVENTS = (
    "title",
    "automatic_promotion",
    "playoff_qualification",
    "promotion",
    "relegation",
)


def read_rows(path: Path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def source_context(matches, complete_seasons, selected_seasons):
    context = {}
    for season in selected_seasons:
        year = int(season[:4])
        target = [
            match
            for match in matches
            if match.fixture.competition_id == LEAGUE_TWO and match.fixture.season_id == season
        ]
        teams = sorted(
            {
                team
                for match in target
                for team in (match.fixture.home_team_id, match.fixture.away_team_id)
            }
        )
        previous_season = f"{year - 1}-{year}"
        previous = complete_seasons.get((LEAGUE_TWO, previous_season), ())
        continuing = {
            team
            for match in previous
            for team in (match.fixture.home_team_id, match.fixture.away_team_id)
        }
        source = complete_seasons.get((NATIONAL_LEAGUE, previous_season))
        strengths = season_strengths(source) if source else None
        for team in teams:
            features = club_features(complete_seasons, LEAGUE_TWO, season, team)
            national = bool(features and features["source_competition"] == NATIONAL_LEAGUE)
            context[season, team] = {
                "cohort": "national_league_entrant"
                if national
                else "continuing"
                if team in continuing
                else "other_entrant",
                "source_quality": float(np.mean(strengths.teams[team].mean)) if national else None,
            }
    quality = [
        row["source_quality"] for row in context.values() if row["source_quality"] is not None
    ]
    median = float(np.median(quality))
    for row in context.values():
        row["source_strength_slice"] = (
            "strong"
            if row["source_quality"] is not None and row["source_quality"] >= median
            else "weak"
            if row["source_quality"] is not None
            else None
        )
    return context, median


def paired_rows(control, candidate, context):
    def key(row):
        return row["season_id"], row["origin"], row["team_id"]

    left, right = ({key(row): row for row in rows} for rows in (control, candidate))
    if left.keys() != right.keys():
        raise ValueError("Control and candidate season-panel cases differ")
    rows = []
    truth_fields = ("actual_points", "actual_rank")
    for case in sorted(left):
        a, b = left[case], right[case]
        if any(a[field] != b[field] for field in truth_fields):
            raise ValueError(f"Control and candidate truth differs for {case}")
        base = {
            "season_id": a["season_id"],
            "origin": a["origin"],
            "team_id": a["team_id"],
            **context[a["season_id"], a["team_id"]],
        }
        rows.append(
            {
                **base,
                **{
                    f"control_{metric}": float(a[metric])
                    for metric in METRICS
                    if a.get(metric) not in (None, "")
                },
                **{
                    f"candidate_{metric}": float(b[metric])
                    for metric in METRICS
                    if b.get(metric) not in (None, "")
                },
                **{
                    f"control_{event}_{suffix}": float(a[f"{event}_{suffix}"])
                    for event in EVENTS
                    for suffix in ("probability", "observed")
                    if a.get(f"{event}_{suffix}") not in (None, "")
                },
                **{
                    f"candidate_{event}_{suffix}": float(b[f"{event}_{suffix}"])
                    for event in EVENTS
                    for suffix in ("probability", "observed")
                    if b.get(f"{event}_{suffix}") not in (None, "")
                },
                "control_points_pit": float(a["pit"]),
                "candidate_points_pit": float(b["pit"]),
                "control_rank_pit": float(a["rank_pit"]),
                "candidate_rank_pit": float(b["rank_pit"]),
            }
        )
    return rows


def selected_scope(rows, scope):
    if scope == "all_league_two":
        return rows
    if scope == "national_league_entrants":
        return [row for row in rows if row["cohort"] == "national_league_entrant"]
    if scope == "continuing_clubs":
        return [row for row in rows if row["cohort"] == "continuing"]
    return [row for row in rows if row["source_strength_slice"] == scope]


def comparisons(rows, samples, seed):
    results, by_season = [], []
    scopes = ("all_league_two", "national_league_entrants", "continuing_clubs", "strong", "weak")
    rng = np.random.default_rng(seed)
    for scope in scopes:
        scoped = selected_scope(rows, scope)
        for origin in ("preseason", "MW6", "MW12", "MW19", "MW30"):
            origin_rows = [row for row in scoped if row["origin"] == origin]
            seasons = sorted({row["season_id"] for row in origin_rows})
            if not seasons:
                continue
            for metric in METRICS:
                usable = [
                    row
                    for row in origin_rows
                    if f"control_{metric}" in row and f"candidate_{metric}" in row
                ]
                if not usable:
                    continue
                effects = {
                    season: [
                        row[f"candidate_{metric}"] - row[f"control_{metric}"]
                        for row in usable
                        if row["season_id"] == season
                    ]
                    for season in seasons
                }
                effects = {season: values for season, values in effects.items() if values}
                for season, values in effects.items():
                    by_season.append(
                        {
                            "scope": scope,
                            "origin": origin,
                            "metric": metric,
                            "season_id": season,
                            "cases": len(values),
                            "candidate_minus_control": float(np.mean(values)),
                        }
                    )
                season_ids = sorted(effects)
                draws = np.empty(0)
                if len(season_ids) >= 6:
                    sums = np.array([sum(effects[season]) for season in season_ids])
                    counts = np.array([len(effects[season]) for season in season_ids])
                    indices = rng.integers(0, len(season_ids), size=(samples, len(season_ids)))
                    draws = sums[indices].sum(axis=1) / counts[indices].sum(axis=1)
                values = [value for season in season_ids for value in effects[season]]
                results.append(
                    {
                        "scope": scope,
                        "origin": origin,
                        "metric": metric,
                        "seasons": len(season_ids),
                        "matched_cases": len(values),
                        "candidate_minus_control": float(np.mean(values)),
                        "interval_lower": float(np.quantile(draws, 0.025)) if len(draws) else None,
                        "interval_upper": float(np.quantile(draws, 0.975)) if len(draws) else None,
                        "interval_method": "whole-season bootstrap"
                        if len(draws)
                        else "not estimated",
                    }
                )
    return results, by_season


def calibration(rows):
    result = []
    for scope in ("all_league_two", "national_league_entrants"):
        scoped = selected_scope(rows, scope)
        for origin in ("preseason", "MW6", "MW12", "MW19", "MW30"):
            selected = [row for row in scoped if row["origin"] == origin]
            for model in ("control", "candidate"):
                for event in ("points_pit", "rank_pit", *EVENTS):
                    probability = event if event.endswith("_pit") else f"{event}_probability"
                    key = f"{model}_{probability}"
                    if not selected or key not in selected[0]:
                        continue
                    for index in range(10):
                        group = [row for row in selected if min(int(row[key] * 10), 9) == index]
                        observed = (
                            len(group) / len(selected)
                            if event.endswith("_pit")
                            else float(np.mean([row[f"{model}_{event}_observed"] for row in group]))
                            if group
                            else None
                        )
                        result.append(
                            {
                                "scope": scope,
                                "origin": origin,
                                "model_id": model,
                                "event": event,
                                "bin_lower": index / 10,
                                "bin_upper": (index + 1) / 10,
                                "count": len(group),
                                "mean_prediction": float(np.mean([row[key] for row in group]))
                                if group
                                else None,
                                "observed_frequency": observed,
                            }
                        )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap-samples", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20260908)
    args = parser.parse_args()
    if args.data.resolve() == Path("data").resolve():
        raise ValueError("Use an empty R2-backed workspace, not the repository data directory")
    load_environment()
    new_run_directory(args.output)
    control = read_rows(args.control / "club_seasons.csv")
    candidate = read_rows(args.candidate / "club_seasons.csv")
    seasons = sorted({row["season_id"] for row in control})
    data = Dataset(args.data)
    try:
        matches = data.matches()
        data_manifest = data.provenance()
    finally:
        data.close()
    complete = completed_seasons(matches, max(match.available_on for match in matches))
    context, median = source_context(matches, complete, seasons)
    paired = paired_rows(control, candidate, context)
    summary, by_season = comparisons(paired, args.bootstrap_samples, args.seed)
    save_rows(args.output / "paired_club_seasons.csv", paired)
    save_rows(args.output / "summary.csv", summary)
    save_rows(args.output / "by_season.csv", by_season)
    save_rows(args.output / "calibration.csv", calibration(paired))
    control_manifest = json.loads((args.control / "manifest.json").read_text())
    candidate_manifest = json.loads((args.candidate / "manifest.json").read_text())
    write_json(
        args.output / "manifest.json",
        {
            "execution": execution_provenance(),
            "main_base_sha": "f3660fe78367243290706acb406055ca422f559c",
            "candidate_sha": candidate_manifest["execution"]["commit"],
            "report_sha": execution_provenance()["commit"],
            "data_authority": "page324-data through an empty R2-backed workspace",
            "data_manifest": data_manifest,
            "control_manifest_sha256": file_hash(args.control / "manifest.json"),
            "candidate_manifest_sha256": file_hash(args.candidate / "manifest.json"),
            "control_training": control_manifest["configs"]["M7"]["models"][1][
                "train_competitions"
            ],
            "candidate_training": candidate_manifest["configs"]["M7"]["models"][1][
                "train_competitions"
            ],
            "seasons": seasons,
            "origins": ["preseason", "MW6", "MW12", "MW19", "MW30"],
            "simulations": candidate_manifest["simulations"],
            "seed": args.seed,
            "matched_cases": len(paired),
            "source_quality_median": median,
            "information_cutoff": candidate_manifest["origin_definition"],
            "historical_evidence_label": "Retrospective development evidence",
            "uncertainty": "Whole-season bootstrap when at least six seasons are available; individual season effects are retained.",
            "limitations": [
                "Historical development results are not fresh confirmation.",
                "The source-conditioned entrant slice has few season clusters.",
                "The 2019-2020 and 2020-2021 League Two seasons are absent from the standard complete-season panel.",
            ],
            "runner_hash": file_hash(Path(__file__)),
        },
    )
    primary = [
        row
        for row in summary
        if row["scope"] == "national_league_entrants"
        and row["metric"] in {"rank_rps", "points_crps", "coverage_90", "width_90"}
    ]
    print(json.dumps({"matched_cases": len(paired), "primary_entrant_results": primary}, indent=2))


if __name__ == "__main__":
    main()
