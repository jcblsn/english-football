import argparse
import json
import sys
import tomllib
from datetime import UTC, date, datetime
from pathlib import Path

from epl_forecast.artifacts import new_run_directory, provenance, results_markdown, write_csv
from epl_forecast.competitions import COMPETITION_IDS
from epl_forecast.data.capture import SourceAccessError
from epl_forecast.datasets import load_dataset
from epl_forecast.evaluation import market_predictions, rolling_predictions, summarize
from epl_forecast.live import LONDON, load_live_season
from epl_forecast.live_forecast import check_freshness, export_forecast
from epl_forecast.models import make_model
from epl_forecast.sanctions import load_sanctions
from epl_forecast.simulation import EuropeScenario
from epl_forecast.storage import file_hash, write_json
from epl_forecast.training import training_matches


def load_config(path: Path) -> dict:
    with path.open("rb") as stream:
        config = tomllib.load(stream)
    previous_end = None
    for split in ("development", "validation", "holdout"):
        start, end = (date.fromisoformat(config[f"{split}_{part}"]) for part in ("start", "end"))
        if start >= end or (previous_end and start < previous_end):
            raise ValueError("Experiment splits must be chronological, nonoverlapping intervals")
        previous_end = end
    if config["train_window_days"] < 1 or config["min_train_matches"] < 1:
        raise ValueError("Training limits must be positive")
    for spec in config["models"]:
        spec.setdefault("parameters", {})["competition_id"] = config["competition_id"]
    return config


def fitted_model(matches: list, config: dict, model_id: str, as_of: date):
    specs = [spec for spec in config["models"] if spec["id"] == model_id]
    if len(specs) != 1:
        raise ValueError(f"Unknown or duplicate model ID: {model_id}")
    training = training_matches(matches, config, specs[0], as_of)
    return make_model(specs[0]).fit(training, as_of), specs[0], training


def save_rows(path: Path, rows: list[dict]) -> None:
    if rows:
        write_csv(path, list(dict.fromkeys(key for row in rows for key in row)), rows)


def evaluate_command(args) -> None:
    config = load_config(args.config)
    matches, odds, manifest = load_dataset(args.data)
    start = date.fromisoformat(config[f"{args.split}_start"])
    end = date.fromisoformat(config[f"{args.split}_end"])
    new_run_directory(args.output)
    predictions = rolling_predictions(matches, config, start, end, progress=True)
    markets = market_predictions(predictions, odds)
    summary = summarize(predictions, markets, config)
    evaluation_context = {
        key: config[key] for key in ("evaluation_status", "evaluation_note") if key in config
    }
    summary.update(evaluation_context)
    save_rows(args.output / "predictions.csv", predictions)
    save_rows(args.output / "market_predictions.csv", markets)
    for key in ("overall", "by_season", "calibration", "market_matched"):
        save_rows(args.output / f"{key}.csv", summary[key])
    write_json(args.output / "paired_comparisons.json", summary["paired_comparisons"])
    write_json(args.output / "summary.json", summary)
    write_json(
        args.output / "run.json",
        {
            **provenance(config, manifest),
            **evaluation_context,
            "split": args.split,
            "start": str(start),
            "end": str(end),
            "information_cutoff": "start of match date; no same-day results",
        },
    )
    report = results_markdown(summary)
    (args.output / "results.md").write_text(report)
    print(report)


def forecast_command(args) -> None:
    live = load_live_season(args.data, args.cutoff, args.competition, args.season)
    check_freshness(live, args.max_snapshot_age_hours)
    config = load_config(args.config)
    config["competition_id"] = live.competition_id
    for model in config["models"]:
        model.setdefault("parameters", {})["competition_id"] = live.competition_id
        if "data_root" in model.get("parameters", {}):
            model["parameters"]["data_root"] = str(args.data)
            model["parameters"]["data_cutoff"] = live.observed_at.isoformat()
    history, odds, manifest = load_dataset(args.data, live.observed_at)
    history = [
        match
        for match in history
        if (match.fixture.competition_id, match.fixture.season_id)
        != (live.competition_id, live.season_id)
    ] + live.played
    as_of = live.observed_at.astimezone(LONDON).date()
    model, spec, training = fitted_model(history, config, args.model, as_of)
    europe = (
        EuropeScenario(**json.loads(args.europe_scenario.read_text()))
        if args.europe_scenario
        else None
    )
    adjustments = (
        json.loads(args.adjustments.read_text())
        if args.adjustments
        else load_sanctions(args.data, live.observed_at).known_adjustments(
            live.competition_id, live.season_id, as_of
        )
    )
    output = args.output or Path("runs/forecasts") / datetime.now(UTC).strftime(
        "%Y-%m-%dT%H%M%S.%fZ"
    )
    market_pool = json.loads(args.market_pool.read_text()) if args.market_pool else None
    if market_pool and market_pool["structural_model_id"] != args.model:
        market_pool = None
    market_quotes = [
        quote
        for quote in odds
        if (quote["competition_id"], quote["season_id"]) == (live.competition_id, live.season_id)
    ]
    result = export_forecast(
        live,
        model,
        training,
        {
            **provenance(config, manifest),
            "model": spec,
            "data_cutoff": live.observed_at.isoformat(),
            "live_snapshot": live.manifest,
            "seed": args.seed,
            "simulations": args.simulations,
            "max_goals": args.max_goals,
            "europe_scenario": None if europe is None else vars(europe),
            "adjustments": adjustments,
            "market_pool": None
            if market_pool is None
            else {**market_pool, "config_sha256": file_hash(args.market_pool)},
        },
        output,
        args.simulations,
        args.seed,
        args.max_goals,
        adjustments,
        europe,
        market_quotes,
        market_pool,
    )
    print(
        f"Archived {len(result['matches'])} match forecasts and "
        f"{len(result['team_strengths'])} team strengths to {output}"
    )
    if result["simulation"]:
        print(
            f"Fixed {len(live.played)} captured full-time results; "
            f"simulated {len(live.remaining)} fixtures {args.simulations:,} times"
        )
    else:
        print(result["simulation_unavailable_reason"])
    print(f"Open {output / 'index.html'}")


def operate_command(args) -> None:
    import shutil

    from epl_forecast.pipeline import install_launch_agent, operate

    if args.install_launch_agent:
        uv = shutil.which("uv")
        if uv is None:
            raise ValueError("uv must be installed")
        path = install_launch_agent(
            "org.epl-forecast.operate",
            [
                uv,
                "run",
                "--locked",
                "epl-forecast",
                "operate",
                "--data",
                str(args.data.resolve()),
                "--site",
                str(args.site.resolve()),
                "--runs",
                str(args.runs.resolve()),
                "--simulations",
                str(args.simulations),
            ],
            args.runs,
            3600,
            logs="operate",
        )
        print(f"Installed the product pipeline agent: {path}")
        return
    result = operate(
        args.data,
        args.site,
        args.runs,
        args.simulations,
        None,
        args.force,
        not args.no_collect,
    )
    print(json.dumps({k: v for k, v in result.items() if k != "collection"}, indent=2))
    if result["status"] in ("failed", "skipped"):
        raise SystemExit(1)


def verify_command(args) -> None:
    from epl_forecast.verification import verify_archives

    report = verify_archives(args.archive, args.data, args.output)
    if report["failures"]:
        raise SystemExit(f"{report['failures']} product checks failed")


def datawrapper_poc_command(args) -> None:
    from epl_forecast.datawrapper import publish

    print(json.dumps(publish(args.site, args.config, args.env), indent=2))


def materialize_command(args) -> None:
    from epl_forecast.publication import materialize_publication
    from epl_forecast.storage import R2Store

    result = materialize_publication(R2Store.from_environment("R2_PUBLISH_BUCKET"), args.site)
    print(json.dumps(result, indent=2))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Probabilistic forecasts and season simulation for England's four league divisions"
    )
    commands = root.add_subparsers(dest="command", required=True)
    forecast = commands.add_parser("forecast", help="Archive a current-season score-model forecast")
    forecast.add_argument("--cutoff", type=datetime.fromisoformat)
    forecast.add_argument("--competition", choices=COMPETITION_IDS, default=COMPETITION_IDS[0])
    forecast.add_argument("--season")
    forecast.add_argument("--config", type=Path, default=Path("configs/product.toml"))
    forecast.add_argument("--data", type=Path, default=Path("data"))
    forecast.add_argument("--output", type=Path)
    forecast.add_argument("--model", default="M7-xg-v1")
    forecast.add_argument("--simulations", type=int, default=10000)
    forecast.add_argument("--seed", type=int, default=20260905)
    forecast.add_argument("--max-goals", type=int, default=10)
    forecast.add_argument("--max-snapshot-age-hours", type=float, default=24)
    forecast.add_argument("--europe-scenario", type=Path)
    forecast.add_argument("--adjustments", type=Path)
    forecast.add_argument("--market-pool", type=Path, default=Path("configs/market_pool.json"))
    forecast.set_defaults(func=forecast_command)
    operate = commands.add_parser(
        "operate", help="Collect, forecast every division, verify and publish derived artifacts"
    )
    operate.add_argument("--data", type=Path, default=Path("data"))
    operate.add_argument("--site", type=Path, default=Path("site"))
    operate.add_argument("--runs", type=Path, default=Path("runs/product"))
    operate.add_argument("--simulations", type=int, default=10000)
    operate.add_argument("--force", action="store_true")
    operate.add_argument("--no-collect", action="store_true")
    operate.add_argument("--install-launch-agent", action="store_true")
    operate.set_defaults(func=operate_command)
    verify = commands.add_parser(
        "verify", help="Check forecast archives against the product contract"
    )
    verify.add_argument("--archive", type=Path, nargs="+", required=True)
    verify.add_argument("--data", type=Path, default=Path("data"))
    verify.add_argument("--output", type=Path, required=True)
    verify.set_defaults(func=verify_command)
    datawrapper = commands.add_parser(
        "datawrapper-poc", help="Run the temporary Page 324 Datawrapper smoke test"
    )
    datawrapper.add_argument("--site", type=Path, default=Path("site"))
    datawrapper.add_argument("--config", type=Path, default=Path("configs/datawrapper_poc.toml"))
    datawrapper.add_argument("--env", type=Path, default=Path(".env"))
    datawrapper.set_defaults(func=datawrapper_poc_command)
    materialize = commands.add_parser(
        "materialize", help="Build the static publication data from R2"
    )
    materialize.add_argument("--site", type=Path, default=Path("site"))
    materialize.set_defaults(func=materialize_command)
    evaluate = commands.add_parser(
        "evaluate", help="Score rolling historical match forecasts for M7 and M2"
    )
    evaluate.add_argument("--config", type=Path, default=Path("configs/product.toml"))
    evaluate.add_argument("--data", type=Path, default=Path("data"))
    evaluate.add_argument("--output", type=Path, required=True)
    evaluate.add_argument(
        "--split", choices=["development", "validation", "holdout"], required=True
    )
    evaluate.set_defaults(func=evaluate_command)
    return root


def main() -> None:
    from epl_forecast.storage import load_environment

    load_environment()
    if len(sys.argv) > 1 and sys.argv[1] == "data":
        from epl_forecast.data.collect import main as data_main

        sys.argv.pop(1)
        data_main()
        return
    root = parser()
    args = root.parse_args()
    try:
        args.func(args)
    except (ValueError, SourceAccessError, OSError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
