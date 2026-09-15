"""Export pooled season score comparisons and calibration figures."""

import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from epl_forecast.artifacts import retain_execution
from epl_forecast.cli import save_rows
from epl_forecast.season_evaluation import summarize

ORIGINS = ["preseason", "MW6", "MW12", "MW19", "MW30"]


def read_rows(path):
    with path.open() as stream:
        return list(csv.DictReader(stream))


def paired_comparisons(rows, seed=20260908, samples=10000, baseline_model="M2"):
    lookup = {(r["model_id"], r["origin"], r["season_id"], r["team_id"]): r for r in rows}
    if len(lookup) != len(rows):
        raise ValueError("Duplicate club-season origins")
    baseline_keys = {(o, s, t) for m, o, s, t in lookup if m == baseline_model}
    models = [baseline_model, *sorted({r["model_id"] for r in rows} - {baseline_model})]
    for model in models:
        if {(o, s, t) for m, o, s, t in lookup if m == model} != baseline_keys:
            raise ValueError("Models must have matched club-season origins")
    event_metrics = sorted(
        key
        for key in rows[0]
        if key.endswith("_brier") and all(row.get(key) not in (None, "") for row in rows)
    )
    rng = np.random.default_rng(seed)
    output = []
    for origin in ORIGINS:
        baseline = [r for r in rows if r["model_id"] == baseline_model and r["origin"] == origin]
        seasons = sorted({r["season_id"] for r in baseline})
        indices = rng.integers(0, len(seasons), size=(samples, len(seasons)))
        for model in models[1:]:
            for metric in ("rank_rps", "points_crps", *event_metrics):
                grouped = []
                for season in seasons:
                    differences = [
                        float(lookup[model, origin, season, r["team_id"]][metric])
                        - float(r[metric])
                        for r in baseline
                        if r["season_id"] == season
                    ]
                    expected = sum(
                        r["season_id"] == season and r["origin"] == origin for r in baseline
                    )
                    if len(differences) != expected or expected not in (20, 24):
                        raise ValueError("Paired comparisons require complete seasons")
                    grouped.append(np.mean(differences))
                delta = np.array(grouped)
                lo, hi = np.quantile(delta[indices].mean(axis=1), [0.025, 0.975])
                output.append(
                    {
                        "model_id": model,
                        "origin": origin,
                        "metric": metric,
                        f"difference_vs_{baseline_model}": float(delta.mean()),
                        "season_cluster_ci_low": float(lo),
                        "season_cluster_ci_high": float(hi),
                        "club_seasons": len(baseline),
                        "seasons": len(seasons),
                    }
                )
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", default="M2")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    retain_execution(args.output)
    rows = read_rows(args.evaluation / "club_seasons.csv")
    calibration = read_rows(args.evaluation / "calibration.csv")
    summary = read_rows(args.evaluation / "summary.csv")
    models = [args.baseline, *sorted({r["model_id"] for r in rows} - {args.baseline})]
    numeric_rows = []
    for row in rows:
        converted = {}
        for key, value in row.items():
            if key == "promoted":
                converted[key] = value == "True"
            elif key in (
                "competition_id",
                "model_id",
                "origin",
                "season_id",
                "team_id",
                "as_of",
                "entry_cohort",
            ):
                converted[key] = value
            else:
                converted[key] = float(value)
        numeric_rows.append(converted)
    subgroup_scores = []
    subgroups = sorted({r.get("entry_cohort", "") for r in numeric_rows} - {""})
    if not subgroups:
        subgroups = [True, False]
    for subgroup in subgroups:
        selected = [
            r
            for r in numeric_rows
            if r.get("entry_cohort") == subgroup
            or (not r.get("entry_cohort") and r["promoted"] == subgroup)
        ]
        scores, _ = summarize(selected)
        label = subgroup if isinstance(subgroup, str) else "promoted" if subgroup else "incumbent"
        subgroup_scores.extend({"subgroup": label, **r} for r in scores)
    save_rows(args.output / "subgroups.csv", subgroup_scores)
    save_rows(
        args.output / "paired_comparisons.csv",
        paired_comparisons(rows, baseline_model=args.baseline),
    )
    fig, axes = plt.subplots(
        5, len(models), figsize=(4 * len(models), 15), sharex=True, sharey=True
    )
    for i, origin in enumerate(ORIGINS):
        for j, model in enumerate(models):
            ax = axes[i, j]
            selected = [
                r
                for r in calibration
                if r["model_id"] == model and r["origin"] == origin and r["event"] == "points_pit"
            ]
            ax.bar(
                [float(r["bin_lower"]) for r in selected],
                [float(r["observed_frequency"]) for r in selected],
                width=0.1,
                align="edge",
                edgecolor="white",
            )
            ax.axhline(0.1, color="black", linestyle="--", linewidth=1)
            ax.set_title(f"{model} · {origin}")
            ax.set_xlim(0, 1)
    counts = sorted({int(r["club_seasons"]) for r in summary})
    fig.suptitle(f"Randomized points PIT · club-seasons per panel: {counts}")
    fig.supxlabel("PIT")
    fig.supylabel("Fraction of club-seasons")
    fig.tight_layout()
    fig.savefig(args.output / "points_pit.png", dpi=150)
    plt.close(fig)
    fig, axes = plt.subplots(
        5, len(models), figsize=(4 * len(models), 15), sharex=True, sharey=True
    )
    for i, origin in enumerate(ORIGINS):
        for j, model in enumerate(models):
            ax = axes[i, j]
            selected = [
                r
                for r in calibration
                if r["model_id"] == model and r["origin"] == origin and r["event"] == "rank_pit"
            ]
            ax.bar(
                [float(r["bin_lower"]) for r in selected],
                [float(r["observed_frequency"]) for r in selected],
                width=0.1,
                align="edge",
                edgecolor="white",
            )
            ax.axhline(0.1, color="black", linestyle="--", linewidth=1)
            ax.set_title(f"{model} · {origin}")
            ax.set_xlim(0, 1)
    fig.suptitle(f"Randomized rank PIT · club-seasons per panel: {counts}")
    fig.supxlabel("PIT")
    fig.supylabel("Fraction of club-seasons")
    fig.tight_layout()
    fig.savefig(args.output / "rank_pit.png", dpi=150)
    plt.close(fig)
    events = sorted(
        {r["event"] for r in calibration if r["event"] not in {"points_pit", "rank_pit"}}
    )
    fig, axes = plt.subplots(
        5, len(events), figsize=(4 * len(events), 18), sharex=True, sharey=True, squeeze=False
    )
    for i, origin in enumerate(ORIGINS):
        for j, event in enumerate(events):
            ax = axes[i, j]
            ax.plot([0, 1], [0, 1], "k--", linewidth=1)
            for model in models:
                selected = [
                    r
                    for r in calibration
                    if r["model_id"] == model
                    and r["origin"] == origin
                    and r["event"] == event
                    and int(r["count"])
                ]
                x = [float(r["mean_prediction"]) for r in selected]
                y = [float(r["observed_frequency"]) for r in selected]
                (line,) = ax.plot(x, y, label=model, linewidth=1)
                ax.scatter(
                    x, y, s=[8 + int(r["count"]) / 2 for r in selected], color=line.get_color()
                )
            ax.set_title(f"{origin} · {event}")
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
    axes[0, 0].legend()
    fig.suptitle("Event reliability · marker area reflects bin count; sparse bins are noisy")
    fig.supxlabel("Mean forecast probability")
    fig.supylabel("Observed frequency")
    fig.tight_layout()
    fig.savefig(args.output / "event_reliability.png", dpi=150)
    plt.close(fig)
    fig, axes = plt.subplots(1, 4, figsize=(16, 4), sharey=True)
    for ax, level in zip(axes, (50, 80, 90, 95), strict=True):
        for model in models:
            selected = {r["origin"]: r for r in summary if r["model_id"] == model}
            ax.plot(
                ORIGINS,
                [float(selected[o][f"coverage_{level}"]) for o in ORIGINS],
                marker="o",
                label=model,
            )
        ax.axhline(level / 100, color="black", linestyle="--")
        ax.set_title(f"{level}% central points interval")
        ax.set_ylim(0, 1)
        ax.tick_params(axis="x", rotation=30)
    axes[0].legend()
    fig.supylabel("Empirical coverage")
    fig.tight_layout()
    fig.savefig(args.output / "points_coverage.png", dpi=150)
    plt.close(fig)
    fig, axes = plt.subplots(1, 3, figsize=(13, 4), sharey=True)
    for ax, level in zip(axes, (50, 80, 90), strict=True):
        for model in models:
            selected = {r["origin"]: r for r in summary if r["model_id"] == model}
            ax.plot(
                ORIGINS,
                [float(selected[o][f"rank_coverage_{level}"]) for o in ORIGINS],
                marker="o",
                label=model,
            )
        ax.axhline(level / 100, color="black", linestyle="--")
        ax.set_title(f"{level}% central rank interval")
        ax.set_ylim(0, 1)
        ax.tick_params(axis="x", rotation=30)
    axes[0].legend()
    fig.supylabel("Empirical coverage")
    fig.tight_layout()
    fig.savefig(args.output / "rank_coverage.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    main()
