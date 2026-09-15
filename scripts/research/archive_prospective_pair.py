"""Archive a matched prospective control and candidate forecast from one cutoff.

Both forecasts use the same code, data cutoff, seed and path count. The control
removes one training competition from the target division. Both archives must
pass the product checks. The pair is kept in R2 also if the candidate is later
rejected.
"""

import argparse
import json
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from epl_forecast.cloud import sync_tree
from epl_forecast.competitions import COMPETITION_IDS
from epl_forecast.storage import R2Store, file_hash, load_environment, write_json

REPOSITORY = Path(__file__).resolve().parents[2]


def control_config(product: Path, competition: str, excluded: str) -> str:
    text = product.read_text()
    config = tomllib.loads(text)
    spec = next(s for s in config["models"] if s["id"] == "M7-xg-v1")
    sources = spec["train_competitions"][competition]
    if excluded not in sources:
        raise ValueError(f"{excluded} is not a training competition of {competition}")
    old = f"{competition} = {json.dumps(sources, separators=(', ', ': '))}"
    new = f"{competition} = {json.dumps([s for s in sources if s != excluded], separators=(', ', ': '))}"
    if text.count(old) != 1:
        raise ValueError("The product configuration layout is not recognized")
    return text.replace(old, new)


def run(command: list[str], log: Path) -> None:
    result = subprocess.run(command, cwd=REPOSITORY, text=True, capture_output=True, check=False)
    log.write_text(result.stdout + result.stderr)
    if result.returncode:
        raise SystemExit(f"Command failed; see {log}")


def git_sha() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPOSITORY, text=True, capture_output=True, check=True
    ).stdout.strip()


def main():
    load_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--competition", choices=COMPETITION_IDS, required=True)
    parser.add_argument("--exclude", required=True, help="Training competition the control omits")
    parser.add_argument("--config", type=Path, default=Path("configs/product.toml"))
    parser.add_argument("--output", type=Path, default=Path("runs/prospective"))
    parser.add_argument("--simulations", type=int, default=10000)
    parser.add_argument("--no-upload", action="store_true")
    args = parser.parse_args()

    cutoff = datetime.now(UTC).replace(microsecond=0)
    run_id = cutoff.strftime("%Y%m%dT%H%M%SZ")
    root = args.output / args.experiment / args.competition / run_id
    root.mkdir(parents=True)
    configs = {"candidate": args.config, "control": root / "control.toml"}
    configs["control"].write_text(control_config(args.config, args.competition, args.exclude))
    for arm, config in configs.items():
        workspace = root / "workspaces" / arm
        workspace.mkdir(parents=True)
        run(
            [
                sys.executable,
                "-m",
                "epl_forecast.cli",
                "forecast",
                "--data",
                str(workspace),
                "--competition",
                args.competition,
                "--cutoff",
                cutoff.isoformat(),
                "--config",
                str(config),
                "--simulations",
                str(args.simulations),
                "--output",
                str(root / arm),
            ],
            root / f"{arm}-forecast.log",
        )
        run(
            [
                sys.executable,
                "-m",
                "epl_forecast.cli",
                "verify",
                "--archive",
                str(root / arm),
                "--data",
                str(workspace),
                "--output",
                str(root / f"{arm}-verification"),
            ],
            root / f"{arm}-verify.log",
        )
    write_json(
        root / "pair.json",
        {
            "experiment": args.experiment,
            "competition_id": args.competition,
            "cutoff": cutoff.isoformat(),
            "code_sha": git_sha(),
            "control_excludes": args.exclude,
            "config_sha256": {arm: file_hash(path) for arm, path in configs.items()},
            "simulations": args.simulations,
            "information_convention": "one shared data cutoff; archived before the matches it forecasts",
        },
    )
    if args.no_upload:
        print(root)
        return
    store = R2Store.from_environment("R2_DATA_BUCKET")
    prefix = f"research/evidence/{args.experiment}/prospective/{args.competition}/{run_id}"
    uploaded = 0
    for path in sorted(root.iterdir()):
        if path.name == "workspaces":
            continue
        if path.is_dir():
            uploaded += sync_tree(path, store, f"{prefix}/{path.name}")["uploaded"]
        else:
            store.upload(path, f"{prefix}/{path.name}", immutable=True)
            uploaded += 1
    print(f"Archived {uploaded} files to {prefix}")


if __name__ == "__main__":
    main()
