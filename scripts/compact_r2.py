"""Compact canonical observations and switch the R2 manifest pointer."""

import json
from pathlib import Path

from epl_forecast.cloud import compact_canonical
from epl_forecast.storage import R2Store, load_environment


def main() -> None:
    load_environment()
    result = compact_canonical(Path("data"), R2Store.from_environment("R2_DATA_BUCKET"))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
