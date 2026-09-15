"""Compact canonical observations and switch the R2 manifest pointer."""

import argparse
import json
from pathlib import Path

from epl_forecast.cloud import compact_canonical, compaction_due
from epl_forecast.storage import R2Store, load_environment


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--max-incremental-batches", type=int, default=250)
    args = parser.parse_args()
    load_environment()
    store = R2Store.from_environment("R2_DATA_BUCKET")
    if not args.force and not compaction_due(store, args.max_incremental_batches):
        print(json.dumps({"status": "not_due"}, indent=2))
        return
    result = compact_canonical(Path("data"), store)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
