"""Replay the R2 raw captures with the current normalizers, and optionally publish the result."""

import argparse
import json

from epl_forecast.data.replay import replay_canonical
from epl_forecast.storage import R2Store, load_environment


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Replace the canonical catalog with the replayed history. Without it, only report.",
    )
    args = parser.parse_args()
    load_environment()
    result = replay_canonical(R2Store.from_environment("R2_DATA_BUCKET"), publish=args.publish)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
