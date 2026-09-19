"""Build a read-only object disposition manifest for an authorized migration."""

from datetime import UTC, datetime

from epl_forecast.competitions import COMPETITION_IDS


def _pointer_targets(store) -> set[str]:
    targets = set()
    pointers = [store.get_json("state/canonical-snapshot.json")]
    pointers.extend(
        store.get_json(f"state/{kind}/{competition_id}.json")
        for kind in ("fits", "results")
        for competition_id in COMPETITION_IDS
    )
    for pointer in pointers:
        if not pointer:
            continue
        for field in ("database_key", "manifest_key"):
            if pointer.get(field):
                targets.add(pointer[field])
    return targets


def build_retention_plan(store) -> dict:
    """Return exact deletion candidates without changing remote state."""
    catalog = store.get_json("state/manifests.json", {"manifests": []})
    manifests = catalog.get("manifests", [])
    protected = _pointer_targets(store)
    protected.update(f"manifests/{item['batch_id']}.json" for item in manifests)
    protected.update(file["path"] for item in manifests for file in item.get("files", []))

    reasons = {
        "parquet/": "not referenced by the selected canonical catalog",
        "manifests/": "not selected by the canonical catalog",
        "snapshots/": "not named by the canonical snapshot pointer",
        "fits/": "not named by a current fit pointer",
        "results/": "not named by a current result pointer",
        "runs/forecasts/": "replaced by complete typed results",
        "runs/snapshots/": "replaced by the verified canonical snapshot",
    }
    candidates = []
    for prefix, reason in reasons.items():
        for row in store.inventory(prefix):
            if row["key"] not in protected:
                candidates.append({**row, "reason": reason})

    review = list(store.inventory("research/"))
    candidates.sort(key=lambda row: row["key"])
    review.sort(key=lambda row: row["key"])
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "read_only",
        "protected_objects": sorted(protected),
        "delete_candidates": candidates,
        "review_required": review,
        "summary": {
            "protected_objects": len(protected),
            "delete_candidates": len(candidates),
            "delete_candidate_bytes": sum(row["bytes"] for row in candidates),
            "review_required": len(review),
            "review_required_bytes": sum(row["bytes"] for row in review),
        },
    }


def validate_retention_plan(plan: dict, current: dict) -> None:
    """Reject a saved deletion plan when any relevant live inventory changed."""
    if plan.get("schema_version") != 1 or plan.get("mode") != "read_only":
        raise ValueError("Retention plan is not an applicable read-only plan")
    for field in ("protected_objects", "delete_candidates", "review_required"):
        if plan.get(field) != current.get(field):
            raise ValueError(f"Retention plan is stale: {field} changed")


def retention_status(
    plan: dict,
    data_inventory: list[dict],
    publish_inventory: list[dict],
    policy: dict,
    *,
    now: datetime | None = None,
) -> dict:
    """Report billable occupancy and decide whether an operator must review cleanup."""
    now = now or datetime.now(UTC)
    baseline = policy["baseline"]
    limits = policy["review"]
    research = [row for row in data_inventory if row["key"].startswith("research/")]
    generation_roots = ("snapshots/", "fits/", "results/")
    generations = [
        row for row in plan["delete_candidates"] if row["key"].startswith(generation_roots)
    ]
    data_bytes = sum(row["bytes"] for row in data_inventory)
    publish_bytes = sum(row["bytes"] for row in publish_inventory)
    research_bytes = sum(row["bytes"] for row in research)
    total_objects = len(data_inventory) + len(publish_inventory)
    baseline_objects = baseline["data_objects"] + baseline["publish_objects"]
    recorded_at = datetime.fromisoformat(baseline["recorded_at"])
    measures = {
        "billable_objects": total_objects,
        "billable_bytes": data_bytes + publish_bytes,
        "product_objects": total_objects - len(research),
        "product_bytes": data_bytes + publish_bytes - research_bytes,
        "research_objects": len(research),
        "research_bytes": research_bytes,
        "object_growth": total_objects - baseline_objects,
        "billable_byte_growth": data_bytes
        + publish_bytes
        - baseline["data_bytes"]
        - baseline["publish_bytes"],
        "research_object_growth": len(research) - baseline["research_objects"],
        "research_byte_growth": research_bytes - baseline["research_bytes"],
        "candidate_objects": plan["summary"]["delete_candidates"],
        "candidate_bytes": plan["summary"]["delete_candidate_bytes"],
        "superseded_generations": len(generations),
        "days_since_review": (now - recorded_at).days,
    }
    reasons = []
    checks = (
        ("candidate_objects", ">="),
        ("candidate_bytes", ">="),
        ("superseded_generations", ">="),
        ("object_growth", ">="),
        ("product_bytes", ">="),
        ("research_byte_growth", ">"),
        ("days_since_review", ">="),
    )
    limit_names = {
        "object_growth": "total_object_growth",
        "research_byte_growth": "research_growth_bytes",
        "days_since_review": "days_since_review",
    }
    for measure, comparison in checks:
        limit = limits[limit_names.get(measure, measure)]
        crossed = measures[measure] >= limit if comparison == ">=" else measures[measure] > limit
        if crossed:
            reasons.append(f"{measure} is {measures[measure]}; review limit is {limit}")
    return {
        "schema_version": 1,
        "measured_at": now.isoformat(),
        "baseline": baseline,
        "limits": limits,
        "measures": measures,
        "cleanup_review_required": bool(reasons),
        "review_reasons": reasons,
    }
