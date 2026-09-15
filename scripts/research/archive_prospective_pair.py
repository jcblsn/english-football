"""Archive a matched prospective control and candidate forecast from one cutoff.

Both forecasts use the same code, data cutoff, seed and path count. The control is
the product configuration. The candidate adds M7 parameters to it. Both archives
must pass the product checks. The pair is kept in R2 also if the candidate is later
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
PRODUCT_MODEL = "M7-xg-v1"


def toml_value(value) -> str:
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k} = {toml_value(v)}" for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    return json.dumps(value)


def candidate_config(product: Path, parameters: dict) -> str:
    """The product configuration with extra parameters in the M7 parameter table."""
    text = product.read_text()
    lines = text.splitlines()
    model = next(i for i, line in enumerate(lines) if line == f'id = "{PRODUCT_MODEL}"')
    table = next(i for i in range(model, len(lines)) if lines[i].strip() == "[models.parameters]")
    added = [f"{key} = {toml_value(value)}" for key, value in parameters.items()]
    result = "\n".join([*lines[: table + 1], *added, *lines[table + 1 :]]) + "\n"
    spec = next(s for s in tomllib.loads(result)["models"] if s["id"] == PRODUCT_MODEL)
    if any(spec["parameters"].get(key) != value for key, value in parameters.items()):
        raise ValueError("The candidate parameters did not reach the M7 specification")
    return result


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
    parser.add_argument(
        "--candidate-parameters", type=json.loads, required=True, help="JSON object"
    )
    parser.add_argument("--config", type=Path, default=Path("configs/product.toml"))
    parser.add_argument("--output", type=Path, default=Path("runs/prospective"))
    parser.add_argument("--simulations", type=int, default=10000)
    parser.add_argument("--no-upload", action="store_true")
    args = parser.parse_args()

    cutoff = datetime.now(UTC).replace(microsecond=0)
    run_id = cutoff.strftime("%Y%m%dT%H%M%SZ")
    root = args.output / args.experiment / args.competition / run_id
    root.mkdir(parents=True)
    configs = {"control": args.config, "candidate": root / "candidate.toml"}
    configs["candidate"].write_text(candidate_config(args.config, args.candidate_parameters))
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
            "candidate_parameters": args.candidate_parameters,
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
