import argparse
import json
import os
import sys
import tomllib
from datetime import UTC, date, datetime
from pathlib import Path

from epl_forecast.artifacts import new_run_directory, provenance, results_markdown, write_csv
from epl_forecast.competitions import COMPETITION_IDS
from epl_forecast.data.capture import SourceAccessError
from epl_forecast.datasets import Dataset, load_dataset, timestamp
from epl_forecast.evaluation import market_predictions, rolling_predictions, summarize
from epl_forecast.live import LONDON, load_live_season
from epl_forecast.live_forecast import build_forecast, check_freshness
from epl_forecast.models import make_model
from epl_forecast.personnel import current_adjustments
from epl_forecast.sanctions import load_registry
from epl_forecast.simulation import EuropeScenario
from epl_forecast.storage import file_hash, json_bytes, sha256_bytes, write_json
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


def fitted_model(
    matches: list,
    config: dict,
    model_id: str,
    as_of: date,
    *,
    observations=None,
    fit_store: Path | None = None,
    input_revision: str | None = None,
):
    specs = [spec for spec in config["models"] if spec["id"] == model_id]
    if len(specs) != 1:
        raise ValueError(f"Unknown or duplicate model ID: {model_id}")
    training = training_matches(matches, config, specs[0], as_of)
    if fit_store is None:
        model = make_model(specs[0], observations=observations).fit(training, as_of)
    else:
        if input_revision is None:
            raise ValueError("A fit checkpoint requires an input revision")
        from epl_forecast.fit_state import checkpoint_identity, fitted_model_from_checkpoint

        model, reused = fitted_model_from_checkpoint(
            fit_store,
            specs[0],
            training,
            as_of,
            input_revision,
            observations=observations,
        )
        checkpoint_id, _, _, _, _ = checkpoint_identity(
            specs[0], training, as_of, observations=observations
        )
        model.fit_checkpoint = {
            "checkpoint_id": checkpoint_id,
            "reused": reused,
            "status": model.fit_state_status,
        }
    return model, specs[0], training


def save_rows(path: Path, rows: list[dict]) -> None:
    if rows:
        write_csv(path, list(dict.fromkeys(key for row in rows for key in row)), rows)


def evaluate_command(args) -> None:
    config = load_config(args.config)
    data = Dataset()
    try:
        matches = data.matches()
        odds = data.rows("SELECT * FROM odds")
        manifest = data.provenance()
        observations = data.xg_observations()
    finally:
        data.close()
    start = date.fromisoformat(config[f"{args.split}_start"])
    end = date.fromisoformat(config[f"{args.split}_end"])
    new_run_directory(args.output)
    predictions = rolling_predictions(
        matches, config, start, end, progress=True, observations=observations
    )
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


def forecast_result(args) -> tuple[dict, dict, dict]:
    """Calculate one live forecast and store its authoritative typed result."""
    cutoff = timestamp(args.cutoff) if args.cutoff else datetime.now(UTC)
    if args.snapshot_manifest and not args.snapshot:
        raise ValueError("--snapshot-manifest requires --snapshot")
    if args.result_id and not args.results:
        raise ValueError("--result-id requires --results")
    if args.snapshot:
        from epl_forecast.snapshot import SnapshotDataset

        data = SnapshotDataset(args.snapshot, cutoff, manifest_path=args.snapshot_manifest)
    else:
        data = Dataset(cutoff)
    try:
        live = load_live_season(cutoff, args.competition, args.season, data=data)
        check_freshness(live, args.max_snapshot_age_hours)
        history, odds, manifest = load_dataset(data=data)
        observations = data.xg_observations()
        input_revision = getattr(data, "data_revision", sha256_bytes(json_bytes(manifest)))
        sanctions = load_registry(data)
        personnel = current_adjustments(
            data,
            live.remaining,
            {
                match_id: timestamp(row["kickoff_time"])
                for match_id, row in live.details.items()
                if row["kickoff_time"]
            },
            live.observed_at,
        )
    finally:
        data.close()
    config = load_config(args.config)
    config["competition_id"] = live.competition_id
    for model in config["models"]:
        model.setdefault("parameters", {})["competition_id"] = live.competition_id
        if model.get("parameters", {}).get("canonical_xg"):
            model["parameters"]["data_cutoff"] = live.observed_at.isoformat()
    history = [
        match
        for match in history
        if (match.fixture.competition_id, match.fixture.season_id)
        != (live.competition_id, live.season_id)
    ] + live.played
    as_of = live.observed_at.astimezone(LONDON).date()
    model, spec, training = fitted_model(
        history,
        config,
        args.model,
        as_of,
        observations=observations,
        fit_store=args.fits,
        input_revision=input_revision,
    )
    europe = (
        EuropeScenario(**json.loads(args.europe_scenario.read_text()))
        if args.europe_scenario
        else None
    )
    adjustments = (
        json.loads(args.adjustments.read_text())
        if args.adjustments
        else sanctions.known_adjustments(live.competition_id, live.season_id, as_of)
    )
    market_pool = json.loads(args.market_pool.read_text()) if args.market_pool else None
    if market_pool and market_pool["structural_model_id"] != args.model:
        market_pool = None
    market_quotes = [
        quote
        for quote in odds
        if (quote["competition_id"], quote["season_id"]) == (live.competition_id, live.season_id)
    ]
    run = {
        **provenance(config, manifest),
        "model": spec,
        "fit_checkpoint": getattr(model, "fit_checkpoint", None),
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
    }
    result = build_forecast(
        live,
        model,
        training,
        run,
        args.simulations,
        args.seed,
        args.max_goals,
        adjustments,
        europe,
        market_quotes,
        market_pool,
        personnel=personnel,
    )
    from epl_forecast.results import write_forecast_result

    stored = write_forecast_result(
        args.results,
        result,
        run,
        input_revision=input_revision,
        result_id=args.result_id,
    )
    return result, run, stored


def forecast_command(args) -> None:
    result, _, stored = forecast_result(args)
    print(f"Stored typed forecast result {stored['result_id']} in {args.results}")
    print(
        f"Stored {len(result['matches'])} match forecasts and "
        f"{len(result['team_strengths'])} team strengths"
    )
    if result["simulation"]:
        print(f"Simulated the remaining season {args.simulations:,} times")
    else:
        print(result["simulation_unavailable_reason"])


def operate_command(args) -> None:
    from epl_forecast.pipeline import operate

    result = operate(
        simulations=args.simulations,
        force=args.force,
        collect_first=not args.no_collect,
    )
    print(json.dumps({k: v for k, v in result.items() if k != "collection"}, indent=2))
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a") as stream:
            stream.write(f"published={len(result['published'])}\n")
            stream.write(f"public_changed={str(result['public_changed']).lower()}\n")
    if result["status"] in ("failed", "skipped"):
        raise SystemExit(1)


def snapshot_command(args) -> None:
    from epl_forecast.snapshot import create_snapshot
    from epl_forecast.storage import R2Store

    store = R2Store.from_environment("R2_DATA_BUCKET")
    source_revision = store.identities(["state/manifests.json"])["state/manifests.json"]
    if source_revision is None:
        raise ValueError("The canonical manifest pointer does not exist")
    data = Dataset(store=store, log_http=True)
    try:
        manifest = create_snapshot(data, args.output, source_revision=source_revision)
    finally:
        data.close()
    print(
        json.dumps(
            {
                key: manifest[key]
                for key in (
                    "schema_version",
                    "source_revision",
                    "data_revision",
                    "database_bytes",
                    "database_sha256",
                    "source_http",
                    "source_client",
                )
            },
            indent=2,
        )
    )


def verify_command(args) -> None:
    from epl_forecast.verification import verify_result

    report = verify_result(args.results, args.result_id)
    passed = len(report["checks"]) - report["failures"]
    print(f"{args.result_id}: {passed}/{len(report['checks'])} checks passed")
    for failure in (row for row in report["checks"] if not row["passed"]):
        print(f"  FAILED {failure['check']}: {failure['detail']}")
    if report["failures"]:
        raise SystemExit(f"{report['failures']} product checks failed")


def datawrapper_poc_command(args) -> None:
    from epl_forecast.datawrapper import publish

    print(json.dumps(publish(args.site, args.config, args.env), indent=2))


def materialize_command(args) -> None:
    from epl_forecast.publication import materialize_publication
    from epl_forecast.storage import R2Store

    store = R2Store.from_environment("R2_PUBLISH_BUCKET")
    if args.hindcast_cache_key:
        identity = store.identities(["hindcasts/index.json"])["hindcasts/index.json"] or "none"
        if output := os.environ.get("GITHUB_OUTPUT"):
            with open(output, "a") as stream:
                stream.write(f"cache_key={identity}\n")
        else:
            print(identity)
        return
    result = materialize_publication(
        store,
        args.site,
        tuple(args.archive),
        args.hindcasts,
    )
    print(json.dumps(result, indent=2))


def hindcast_command(args) -> None:
    from epl_forecast.hindcast import run_hindcasts, run_season_bridge
    from epl_forecast.storage import R2Store

    stores = (
        R2Store.from_environment("R2_DATA_BUCKET"),
        R2Store.from_environment("R2_PUBLISH_BUCKET"),
    )
    competitions = tuple(args.competition or COMPETITION_IDS)
    result = (
        run_season_bridge(*stores, competitions, args.season, args.simulations, args.workers)
        if args.bridge
        else run_hindcasts(
            *stores, competitions, tuple(args.seasons), args.simulations, args.workers
        )
    )
    print(json.dumps(result, indent=2))


def match_hindcast_command(args) -> None:
    from epl_forecast.match_hindcast import run_match_hindcasts
    from epl_forecast.storage import R2Store

    result = run_match_hindcasts(
        R2Store.from_environment("R2_DATA_BUCKET"),
        R2Store.from_environment("R2_PUBLISH_BUCKET"),
        tuple(args.competition or COMPETITION_IDS),
        args.season,
        args.workers,
    )
    print(json.dumps(result, indent=2))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Probabilistic forecasts and season simulation for England's four league divisions"
    )
    commands = root.add_subparsers(dest="command", required=True)
    forecast = commands.add_parser("forecast", help="Store a current-season typed forecast result")
    forecast.add_argument("--cutoff", type=datetime.fromisoformat)
    forecast.add_argument("--competition", choices=COMPETITION_IDS, default=COMPETITION_IDS[0])
    forecast.add_argument("--season")
    forecast.add_argument("--config", type=Path, default=Path("configs/product.toml"))
    forecast.add_argument("--model", default="M10-xg-v1")
    forecast.add_argument("--simulations", type=int, default=10000)
    forecast.add_argument("--seed", type=int, default=20260905)
    forecast.add_argument("--max-goals", type=int, default=10)
    forecast.add_argument("--max-snapshot-age-hours", type=float, default=24)
    forecast.add_argument("--snapshot", type=Path)
    forecast.add_argument("--snapshot-manifest", type=Path)
    forecast.add_argument("--results", type=Path, required=True)
    forecast.add_argument("--result-id")
    forecast.add_argument("--fits", type=Path)
    forecast.add_argument("--europe-scenario", type=Path)
    forecast.add_argument("--adjustments", type=Path)
    forecast.add_argument("--market-pool", type=Path, default=Path("configs/market_pool.json"))
    forecast.set_defaults(func=forecast_command)
    operate = commands.add_parser(
        "operate", help="Collect, forecast every division, verify and publish derived artifacts"
    )
    operate.add_argument("--simulations", type=int, default=10000)
    operate.add_argument("--force", action="store_true")
    operate.add_argument("--no-collect", action="store_true")
    operate.set_defaults(func=operate_command)
    snapshot = commands.add_parser(
        "snapshot", help="Create one verified local database from the canonical R2 revision"
    )
    snapshot.add_argument("--output", type=Path, required=True)
    snapshot.set_defaults(func=snapshot_command)
    verify = commands.add_parser("verify", help="Check a typed forecast result")
    verify.add_argument("--results", type=Path, required=True)
    verify.add_argument("--result-id", required=True)
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
    materialize.add_argument(
        "--hindcast-cache-key",
        action="store_true",
        help="Print the current hindcast index identity and do not materialize the site",
    )
    materialize.add_argument(
        "--archive",
        action="append",
        choices=COMPETITION_IDS,
        default=[],
        help="Also materialize one competition archive",
    )
    materialize.add_argument(
        "--hindcasts",
        action="store_true",
        help="Also materialize the hindcast index, season series and weekly documents",
    )
    materialize.set_defaults(func=materialize_command)
    hindcast = commands.add_parser(
        "hindcast", help="Make and publish weekly retrospective hindcasts of completed seasons"
    )
    hindcast.add_argument("--competition", action="append", choices=COMPETITION_IDS)
    hindcast.add_argument("--seasons", nargs="+", type=int, default=list(range(2021, 2026)))
    hindcast.add_argument(
        "--bridge",
        action="store_true",
        help="Make the weekly hindcasts of the season in play, up to live coverage of the version",
    )
    hindcast.add_argument("--season", help="Season identifier for --bridge, such as 2026-2027")
    hindcast.add_argument("--simulations", type=int, default=10000)
    hindcast.add_argument("--workers", type=int, default=4)
    hindcast.set_defaults(func=hindcast_command)
    match_hindcast = commands.add_parser(
        "match-hindcast",
        help="Make retrospective match forecasts from the start of the season until live coverage",
    )
    match_hindcast.add_argument("--competition", action="append", choices=COMPETITION_IDS)
    match_hindcast.add_argument("--season", help="Season identifier, such as 2026-2027")
    match_hindcast.add_argument("--workers", type=int, default=4)
    match_hindcast.set_defaults(func=match_hindcast_command)
    evaluate = commands.add_parser(
        "evaluate", help="Score rolling historical match forecasts for M10 and M2"
    )
    evaluate.add_argument("--config", type=Path, default=Path("configs/product.toml"))
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
