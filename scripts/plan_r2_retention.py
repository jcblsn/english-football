"""Write the read-only R2 retention and deletion-candidate manifest."""

import argparse
import json
import tomllib
from datetime import timedelta
from pathlib import Path

from epl_forecast.retention import build_retention_plan, retention_status
from epl_forecast.storage import R2Store, json_bytes, load_environment, write_immutable


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--policy", type=Path, default=Path("configs/retention.toml"))
    args = parser.parse_args()
    load_environment()
    data_store = R2Store.from_environment("R2_DATA_BUCKET")
    publish_store = R2Store.from_environment("R2_PUBLISH_BUCKET")
    with args.policy.open("rb") as stream:
        policy = tomllib.load(stream)
    retention = policy["retention"]
    plan = build_retention_plan(
        data_store,
        object_grace=timedelta(hours=retention["object_grace_hours"]),
        generation_grace=timedelta(days=retention["generation_grace_days"]),
    )
    plan["retention_status"] = retention_status(
        plan,
        list(data_store.inventory()),
        list(publish_store.inventory()),
        policy,
    )
    write_immutable(args.output, json_bytes(plan))
    if args.summary:
        status = plan["retention_status"]
        measures = status["measures"]
        lines = [
            "# R2 retention dry run",
            "",
            f"- Total billable occupancy: {measures['billable_bytes']} bytes in {measures['billable_objects']} objects",
            f"- Product-only occupancy: {measures['product_bytes']} bytes in {measures['product_objects']} objects",
            f"- Research occupancy: {measures['research_bytes']} bytes; growth is {measures['research_byte_growth']} bytes",
            f"- Deletion candidates: {measures['candidate_objects']} objects and {measures['candidate_bytes']} bytes",
            f"- Grace-protected objects: {plan['summary']['grace_protected']} objects and {plan['summary']['grace_protected_bytes']} bytes",
            f"- Superseded snapshot, fit, or result generations: {measures['superseded_generations']}",
            f"- Cleanup review required: {str(status['cleanup_review_required']).lower()}",
        ]
        lines.extend(f"- Alert: {reason}" for reason in status["review_reasons"])
        args.summary.write_text("\n".join(lines) + "\n")
    print(json.dumps(plan["retention_status"], sort_keys=True))


if __name__ == "__main__":
    main()
