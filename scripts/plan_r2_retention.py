"""Write the read-only R2 retention and deletion-candidate manifest."""

import argparse
from pathlib import Path

from epl_forecast.retention import build_retention_plan
from epl_forecast.storage import R2Store, json_bytes, load_environment, write_immutable


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    load_environment()
    store = R2Store.from_environment("R2_DATA_BUCKET")
    plan = build_retention_plan(store)
    write_immutable(args.output, json_bytes(plan))
    print(plan["summary"])


if __name__ == "__main__":
    main()
