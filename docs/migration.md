# Migration and rollback

This page is the cutover runbook. The owner authorized production writes, workflow cutover and exact-manifest deletion on 2026-09-18, and confirmed backups of both buckets and the complete local directory. Record the final source revision, object manifest and operator before deletion.

## Preconditions

1. Confirm backups of `page324-data`, `page324-publish` and the complete local directory. Record immutable identifiers and test an isolated restore when the backup system exposes those operations.
2. Run `scripts/verify.sh` on the selected code commit.
3. Restore the selected canonical snapshot on a clean runner. Run all four 10,000-path forecasts and all product verifiers from that snapshot.
4. Reconcile canonical table keys, logical hashes, null categories, provider coverage, capture intervals and reviewed identity/rules evidence.
5. Reconcile every retained prospective forecast ID, model version and release receipt. Reconcile every retained hindcast edition and origin.
6. Run the capacity checks in [capacity and retention](capacity.md) with the final inventory. The 12-month base and busy cases must remain below 7 GB.
7. Record explicit authority for workflow changes, production writes and the reviewed deletion manifest.

## Cutover

1. Disable `production.yml` and confirm that no production run is active.
2. Record the final canonical catalog identity. Collect or preserve every capture that arrived after the rehearsal revision.
3. Build and verify the final snapshot, four fit stores and four result stores. Upload immutable database and manifest objects before their conditional pointers.
4. Run the four-division operation from the restored objects. Compare it with the selected reference and run the publication allowlist check before the first release.
5. Enable the new schedule. Observe one complete operation and one Pages deployment. Confirm current pointers, release receipts and the prospective record.
6. Keep the old objects until the smoke check and rollback window finish. Do not dual-write incompatible layouts.

## Retention roots

Protect these roots or exact pointer targets:

- every `raw/` object and `requests/` receipt;
- the selected canonical catalog and each file that it references until collection reads the snapshot directly;
- the database and manifest named by `state/canonical-snapshot.json`;
- each database named by `state/fits/<competition>.json` and `state/results/<competition>.json`;
- operational state, collection audits and reviewed rule or identity evidence;
- all issued public forecast documents, competition archives, current pointers, release receipts and `record.json`;
- every retained public and private hindcast edition;
- the verified backup location and the final pre-cutover revision record.

## Deletion-manifest candidates

Generate exact keys, sizes and ETags. Do not delete from these prefixes by prefix alone. The read-only planner writes the candidate manifest and makes no mutation:

```sh
uv run python scripts/plan_r2_retention.py runs/migration/retention-plan.json
```

| Candidate | Required proof before deletion |
| --- | --- |
| Unreferenced `parquet/` and `manifests/` objects | The selected catalog does not reference the object; snapshot restore and replay reconciliation pass. |
| `runs/forecasts/` | Every issued ID resolves through the typed result store or its compact projection; release receipts and record cohorts agree. |
| `runs/snapshots/` | The selected snapshot pointer restores, verifies and reproduces the reference. |
| Superseded `snapshots/`, `fits/` and `results/` generations | No current pointer names the object; the pointer commit and smoke check completed. |
| `research/` in a product bucket | The reviewed research backup resolves and the owner approves its disposition. |
| Temporary migration or staging keys | The final pointers do not name them and the reconciliation report identifies them as temporary. |

Deletion is free under the current R2 billing rules, but recovery is not. Save the reviewed manifest with the backup evidence and record the deletion result.

## Rollback

Rollback triggers include a snapshot receipt failure, a canonical reconciliation difference, a product verification failure, a missing issued result, a privacy-boundary failure, mixed pointer revisions, a sustained operation over 10 minutes after prepared inputs, or a publication that cannot be reproduced from its typed result.

Disable the writer first. Preserve every post-cutover raw capture and request receipt. Restore the recorded backup and its matching code commit, then restore the last compatible mutable state documents. Do not point old code at new-only state. Re-enable publication only after the restored four-division smoke test passes. If post-cutover captures exist, replay them into the restored line in retrieval order instead of discarding them.

The rollback window ends only after the owner accepts the observed release and the reviewed deletion manifest. The long-term recovery path is the verified backup plus retained raw captures, not a permanent second production writer.

## Completion record

The cutover completed on 19 September 2026 at commit `cbfb9ca1d1006e12230165e7bcae4561c318508a`. Clean workflow runs `35412117186`, `35412237119` and `35413349957` passed checks, production restore and Pages deployment.

The final exact plan protected 2,747 current objects and deleted 50,646 superseded objects totaling 1,680,125,353 bytes. Post-delete verification found zero planned survivors, restored the authoritative analysis session with all 59 issued forecasts, retained all private hindcasts and completed an idle operation from the current snapshot. The production workflow is active.
