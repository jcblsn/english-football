"""Copy the current private archive to the configured R2 data bucket."""

import argparse
import json
from pathlib import Path

from epl_forecast.cloud import sync_data, sync_tree
from epl_forecast.storage import R2Store, load_environment


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--runs", type=Path, default=Path("runs/product"))
    parser.add_argument("--snapshots", type=Path, default=Path("snapshots"))
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--include-private-runs", action="store_true")
    args = parser.parse_args()
    load_environment(args.env)
    store = R2Store.from_environment("R2_DATA_BUCKET")
    result = {"data": sync_data(args.data, store)}
    if args.include_private_runs:
        result["runs"] = sync_tree(args.runs, store, "runs/forecasts")
        result["snapshots"] = sync_tree(args.snapshots, store, "runs/snapshots")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
