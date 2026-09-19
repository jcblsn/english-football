# Capacity and retention

This page records the measured storage unit, the recurring workload model and the limits that must hold before cutover. It separates measurements from projections. All storage values use decimal GB unless a source uses another unit.

## Service limits checked on 18 September 2026

[Cloudflare R2 pricing](https://developers.cloudflare.com/r2/pricing/) includes 10 GB-month of Standard storage, 1 million Class A operations and 10 million Class B operations each month. Standard storage has no retrieval or egress charge. A `PUT`, multipart upload part and `LIST` is Class A. A `GET` or `HEAD` is Class B. The internal limits are stricter: less than 7 GB steady product occupancy, 250,000 Class A operations and 5 million Class B operations each month.

The repository is public and the production workflow uses `ubuntu-latest`. [GitHub states that standard hosted runners are free and unlimited for public repositories](https://docs.github.com/en/actions/reference/runners/github-hosted-runners). The current public Linux runner has 4 CPU cores, 16 GB of memory and 14 GB of SSD storage. This classification does not remove the freshness and runtime requirements.

## Measured pre-cutover state

A read-only inventory of both buckets found 3,072,450,503 bytes on 18 September 2026. The private data bucket held 2,872,719,039 bytes and the publication bucket held 199,731,464 bytes.

| Root | Objects | Bytes | Disposition |
| --- | ---: | ---: | --- |
| `raw/` | 10,452 | 708,999,939 | Retain. New captures use deterministic gzip. |
| `parquet/` | 37,505 | 222,372,620 | Retain only the files referenced by the selected canonical catalog until collection reads the snapshot directly. |
| `manifests/` | 14,558 | 20,737,291 | Retain only the selected catalog and its referenced manifests until collection reads the snapshot directly. |
| `requests/` | 8,940 | 4,313,021 | Retain as immutable capture lineage. |
| `runs/forecasts/` | 1,088 | 946,027,443 | Replace with typed results and compact issued projections after reconciliation. |
| `runs/hindcasts/` and `runs/match-hindcasts/` | 2,501 | 171,573,273 | Retain until retrospective results have a separately verified replacement. |
| `runs/snapshots/` | 161 | 54,383,674 | Replace with the selected canonical snapshot generation. |
| `research/` | 1,624 | 738,048,127 | Not part of the product occupancy plan. Protect it in the approved backup before an authorized move or deletion. |
| Published forecasts, hindcasts and record | 2,621 | 199,731,464 | Retain. |

The final post-retention inventory on 19 September 2026 is 2,316,739,847 bytes: 2,114,434,326 bytes in the private data bucket and 202,305,521 bytes in the publication bucket. The private bucket has 26,310 objects, and the publication bucket has 2,633 objects. After exclusion of the separately protected 738,048,127-byte `research/` archive, current product occupancy is 1.579 GB.

The capacity model keeps a conservative 1.86 GB starting point. It includes the existing raw and request history, the selected canonical catalog, one verified snapshot, four fit stores, a mature 14-day private-result window, compact issued projections, the existing private hindcasts and the current public bucket. The exact cleanup removed the superseded live run archives, canonical batches, snapshot generations and result generations. Current occupancy is below the modeled start because the private-result window is not yet mature and the measured fit stores total 20,758,528 bytes.

## Recurring measurement

The frozen snapshot had 627 manifest batches and was 55,586,816 bytes. A later read-only catalog had 671 batches. Extending the snapshot through those 44 new batches took 17.49 seconds after the prior local snapshot was available. DuckDB made 332 `HEAD` and 83 `GET` requests and read 460,906 bytes. The catalog read was 1,102,712 bytes. Rewriting a compact local snapshot produced 56,373,248 bytes, an increase of 786,432 bytes. Appending into the old physical file instead increased it by 4,718,592 bytes, so the operation uses compact rewrite.

The same 44 batches referenced 33 new raw objects with 6,032,248 original bytes. Deterministic gzip produced 409,082 bytes, which is 6.78% of the original size. The measured delta contained fixture, injury, standings, FPL, Football-Data and Kalshi captures. It is a matchday-like busy delta, not an average day.

The four measured detailed result databases were 8.66 to 11.55 MB for one forecast. The retention model uses the conservative 11.55 MB value for every division. A display-only Championship clone copied all detail in the old design and grew five revisions to 46.41 MB. The lineage design grew the same five revisions to about 14.17 MB, including a one-time schema migration. A lightweight revision points directly to one structural result and stores only effective market and display rows.

The measured four-division 10,000-path calculation finished in 147.51 seconds after prepared inputs were available. The measured 44-batch local extension excludes the download of the prior snapshot and any remote upload. The live cutover verified snapshot, fit and result uploads and restores at current production size.

## Retention contract

| Data | Steady retention |
| --- | --- |
| Original provider evidence and request receipts | Indefinite. New original responses use lossless gzip and retain the hash of the original bytes. |
| Canonical observation history | One current verified snapshot plus the active canonical batches that collection still needs. Remove an unreferenced physical batch only after backup and reconciliation. |
| Snapshot generations | One pointed generation in steady state. Keep the prior object only through the pointer commit and smoke check. Report the two-file overlap as peak storage. |
| Fit state | One pointed cumulative database for each division. Its schema-declared checkpoints can contain more than one logical fitting boundary. |
| Private forecast detail | 14 days. A recent lightweight revision also protects its structural parent. |
| Issued forecast projection and release receipt | Indefinite. One compact projection stays in the typed result database and one sanitized document stays on the public surface. |
| Result database generations | One pointed generation for each division in steady state. The prior immutable generation is a commit-time overlap, not permanent retention. |
| Hindcasts | Retain each released model edition until an explicit product-version disposition removes it. |
| Research and migration evidence | Store outside the steady product roots. Never delete it before the approved backup and disposition check. |

The result writer refuses to expire private detail when the compact issued projection is absent. Recent result lineage is protected. Analysis of an expired result uses the compact typed projection and does not fetch the historical public object. It exposes the retained public grain and labels the synthetic private schema as version 1. Full score, simulation, personnel and provenance detail remains available only inside the 14-day window.

Physical generation deletion is not automatic. The migration run produced and applied one exact object manifest after a fresh inventory match. Routine operation still needs an explicit retention task for superseded generations.

## Workload assumptions

| Input | Base case | Busy case |
| --- | ---: | ---: |
| Scheduled wakes | 8 per day | 8 per day |
| Matchday-like changed deltas | 4 per day | 8 per day on 60 days and 4 per day otherwise |
| Full issued forecasts | 4 per day | 6 per day on 60 days and 4 per day otherwise |
| Detailed result window | 14 days | 14 days |
| New hindcast editions | 1 per year | 1 per year |
| New research/backfill bytes in product buckets | 0 | 0 |
| New analyst cold starts | 30 per month | 300 per month |
| Retry allowance | Included in the operation estimate | 25% of request operations |

The base case treats four wakes as no-change or reusable-source wakes. The busy case applies the measured matchday-like delta at every wake for 60 days. Raw and canonical growth scale from the measured 44-batch delta. Issued projection growth uses the current public forecast average, about 0.289 MB, once in the public bucket and once in the compact typed history. One new hindcast edition uses the current combined private and public edition size, about 0.35 GB. Research and one-off historical backfills are separate capacity events.

## Projection

| Case | Start | New raw | New active canonical batches | Snapshot growth | Capture receipts | Issued projections | Hindcast edition | Projected occupancy |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 12-month base | 1.86 GB | 0.60 GB | 0.67 GB | 1.15 GB | 0.03 GB | 0.84 GB | 0.35 GB | 5.50 GB |
| 12-month busy | 1.86 GB | 0.70 GB | 0.78 GB | 1.34 GB | 0.04 GB | 0.91 GB | 0.35 GB | 5.98 GB |
| 24-month base sensitivity | 1.86 GB | 1.20 GB | 1.34 GB | 2.30 GB | 0.06 GB | 1.68 GB | 0.70 GB | 9.14 GB |
| 24-month busy sensitivity | 1.86 GB | 1.39 GB | 1.57 GB | 2.67 GB | 0.07 GB | 1.83 GB | 0.70 GB | 10.09 GB |

The 12-month cases stay below the internal 7 GB target only after the authorized cleanup and retention policy. The 24-month sensitivities do not. At 6 GB, or no later than nine months after cutover, review canonical partitioning, collection frequency and the duplication between active canonical batches and the snapshot. Do not wait for the R2 free-tier limit.

One changed wake is projected at about 627 Class B and 209 Class A operations before forecast publication. This includes the measured 415 DuckDB source reads, snapshot and catalog reads, immutable-object existence checks and the measured 204 collection objects. Base usage is about 78,000 Class B and 26,000 Class A operations per month. The busy case with the retry allowance is about 112,000 Class B and 38,000 Class A operations per month. Fit, result, publication and analyst operations add less than 5,000 operations per month in this model. Both cases are below the internal and service limits.

At the end of the base year, a changed wake can download and upload a snapshot of about 1.2 GB. R2 egress is free, but time and runner disk are still constraints. The steady file plus commit-time overlap fits the current 14 GB runner disk model. A live remote restore, upload and clean-run bootstrap at projected size must pass before cutover and again before the nine-month review.

## Peaks and exclusions

The final two-bucket live inventory is 2.32 GB before backup compression or versioning. The projection assumes that the protected backup is outside the two steady product buckets. A backup copied into the same R2 product account must be added in full and would consume part of the headroom.

The final retention planner resolved 2,747 protected objects and listed 50,646 deletion candidates with 1,680,125,353 bytes. The candidate total contained 201,719,150 bytes of unreferenced canonical Parquet, 19,710,509 bytes of unselected manifests, 998,912,988 bytes of legacy forecast runs, 54,383,674 bytes of old run snapshots, 56,436,216 bytes of superseded canonical snapshots and 348,962,816 bytes of the four staged result generations. It listed all 1,624 `research/` objects and 738,048,127 bytes separately for review. The exact executor deleted all candidates in 51 requests and found zero survivors. The ignored evidence is at `runs/refactor/m4/final-retention-plan.json` and `runs/refactor/m4/final-retention-report.json`.

Each immutable pointer commit temporarily holds the old and new database. The projection reports only one steady generation. Migration can also hold the 3.07 GB old layout, the new 1.86 GB layout and the backup at the same time. That migration and recovery peak is separate from the steady target.

The capacity gate is live-certified at current production size. The clean `main` runner collected evidence, extended and restored the snapshot, checked all four divisions and completed unchanged. A clean Pages run materialized and validated the complete public surface before deployment. A projected-size restore remains part of the review at 6 GB or nine months after cutover.
