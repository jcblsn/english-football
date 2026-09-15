"""Squad-native imbalance, applied-shift and extreme-case diagnostics for D_squad.

This is validation of the frozen representation, not model selection.
"""

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import numpy as np

from epl_forecast.artifacts import execution_provenance, new_run_directory
from epl_forecast.cli import save_rows
from epl_forecast.storage import write_json

METRICS = ("hda_log_loss", "brier", "score_nll")
BINS = ((0, 0.05), (0.05, 0.10), (0.10, 0.20), (0.20, 0.30), (0.30, 9))


def size_band(size):
    return "<14" if size < 14 else "14-15" if size < 16 else "16-17" if size < 18 else "18+"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--representation", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", type=int, default=30)
    args = parser.parse_args()
    new_run_directory(args.output)
    with (args.representation / "chronological.csv").open() as stream:
        scored = [
            {
                **row,
                **{
                    key: float(row[key])
                    for key in row
                    if key.startswith(("squad_", "control_", "xi_"))
                    and row[key] not in ("", "None")
                },
            }
            for row in csv.DictReader(stream)
        ]
    teams = {}
    with (args.features / "teams.csv").open() as stream:
        for row in csv.DictReader(stream):
            teams[row["match_id"], row["team_id"]] = row
    players = defaultdict(list)
    with (args.features / "players.csv").open() as stream:
        for row in csv.DictReader(stream):
            players[row["match_id"], row["team_id"]].append(row)

    bins = []
    for low, high in BINS:
        chosen = [r for r in scored if low <= abs(r["squad_imbalance"]) < high]
        bins.append(
            {
                "absolute_squad_imbalance": f"{low:.2f}-{high:.2f}" if high < 9 else f">={low:.2f}",
                "matches": len(chosen),
                "mean_absolute_log_rate_shift": float(
                    np.mean([abs(r["squad_delta"]) for r in chosen])
                ),
                **{
                    f"squad_minus_control_{m}": float(
                        np.mean([r[f"squad_{m}"] - r[f"control_{m}"] for r in chosen])
                    )
                    for m in METRICS
                },
            }
        )
    shifts = np.abs([r["squad_delta"] for r in scored])
    quantiles = dict(
        zip(
            ("median", "90%", "99%", "maximum"),
            np.quantile(shifts, [0.5, 0.9, 0.99, 1.0]).tolist(),
            strict=True,
        )
    )

    all_sizes = defaultdict(int)
    for row in teams.values():
        all_sizes[size_band(int(row["target_squad_size"]))] += 1
    ranked = sorted(scored, key=lambda r: abs(r["squad_delta"]), reverse=True)
    top = ranked[: max(1, len(ranked) // 100)]
    top_sizes = defaultdict(int)
    departed_share = []
    for r in top:
        home, away = r["match_id"].split(":")[2:4]
        for team in (home, away):
            meta = teams[r["match_id"], team]
            top_sizes[size_band(int(meta["target_squad_size"]))] += 1
            rows = players[r["match_id"], team]
            absent = sum(float(p["weight"]) for p in rows if p["in_target_squad"] != "True")
            if absent:
                departed_share.append(
                    sum(
                        float(p["weight"])
                        for p in rows
                        if p["in_target_squad"] != "True" and p["departed"] == "True"
                    )
                    / absent
                )

    cases = []
    for r in ranked[: args.cases]:
        home, away = r["match_id"].split(":")[2:4]
        case = {
            "match_id": r["match_id"],
            "season_id": r["season_id"],
            "squad_imbalance": r["squad_imbalance"],
            "xi_imbalance": r["xi_imbalance"],
            "home_log_rate_shift": r["squad_delta"],
            "squad_minus_control_score_nll": r["squad_score_nll"] - r["control_score_nll"],
        }
        for side, team in (("home", home), ("away", away)):
            meta = teams[r["match_id"], team]
            rows = players[r["match_id"], team]
            total = sum(float(p["weight"]) for p in rows)
            absent = sorted(
                (p for p in rows if p["in_target_squad"] != "True"),
                key=lambda p: float(p["weight"]),
                reverse=True,
            )
            case.update(
                {
                    f"{side}_match_date": meta["match_date"],
                    f"{side}_d_squad": sum(float(p["weight"]) for p in absent) / total,
                    f"{side}_target_squad_size": int(meta["target_squad_size"]),
                    f"{side}_minimum_window_squad_size": int(meta["minimum_window_squad_size"]),
                    f"{side}_window_seasons": int(meta["window_seasons"]),
                    f"{side}_window_competitions": int(meta["window_competitions"]),
                    f"{side}_departed_absent_weight": sum(
                        float(p["weight"]) for p in absent if p["departed"] == "True"
                    )
                    / total,
                    f"{side}_largest_absences": "; ".join(
                        f"{p['player_name']} {float(p['weight']) / total:.3f}"
                        f"{' departed' if p['departed'] == 'True' else ''}"
                        for p in absent[:6]
                    ),
                }
            )
        cases.append(case)
    result = {
        "matches": len(scored),
        "imbalance_bins": bins,
        "absolute_shift_quantiles": quantiles,
        "target_squad_sizes_all_team_matches": dict(all_sizes),
        "target_squad_sizes_top_1_percent_shift": dict(top_sizes),
        "top_1_percent_mean_departed_share_of_absent_weight": float(np.mean(departed_share)),
        "mean_departed_share_of_absent_weight_all": float(
            np.mean(
                [
                    sum(
                        float(p["weight"])
                        for p in rows
                        if p["in_target_squad"] != "True" and p["departed"] == "True"
                    )
                    / absent
                    for rows in players.values()
                    if (
                        absent := sum(
                            float(p["weight"]) for p in rows if p["in_target_squad"] != "True"
                        )
                    )
                ]
            )
        ),
    }
    save_rows(args.output / "cases.csv", cases)
    save_rows(args.output / "bins.csv", bins)
    write_json(args.output / "result.json", result)
    write_json(
        args.output / "manifest.json",
        {
            "execution": execution_provenance(),
            "representation": str(args.representation),
            "features": str(args.features),
        },
    )
    print(result)
    for case in cases:
        print(case)


if __name__ == "__main__":
    main()
