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
        "runs/forecasts/": "replaced by typed results and compact issued projections",
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
