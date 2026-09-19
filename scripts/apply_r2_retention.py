"""Apply one exact R2 retention plan after a fresh inventory match."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from epl_forecast.retention import build_retention_plan, validate_retention_plan
from epl_forecast.storage import R2Store, load_environment, write_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    load_environment()
    store = R2Store.from_environment("R2_DATA_BUCKET")
    plan = json.loads(args.plan.read_text())
    current = build_retention_plan(store)
    validate_retention_plan(plan, current)
    keys = [row["key"] for row in plan["delete_candidates"]]
    deleted = store.delete_keys(keys)
    remaining = build_retention_plan(store)
    survivors = sorted(set(keys) & {row["key"] for row in remaining["delete_candidates"]})
    if survivors:
        raise RuntimeError(f"Retention deletion left {len(survivors)} planned objects")
    report = {
        "schema_version": 1,
        "applied_at": datetime.now(UTC).isoformat(),
        "deleted_objects": deleted,
        "deleted_bytes": plan["summary"]["delete_candidate_bytes"],
        "plan": str(args.plan),
        "remaining_candidates": remaining["summary"]["delete_candidates"],
        "remaining_candidate_bytes": remaining["summary"]["delete_candidate_bytes"],
        "metrics": store.metrics(),
    }
    write_json(args.report, report)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
