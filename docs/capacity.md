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
| `runs/forecasts/` | 1,088 | 946,027,443 | Replace with full typed results after reconciliation. |
| `runs/hindcasts/` and `runs/match-hindcasts/` | 2,501 | 171,573,273 | Retain until retrospective results have a separately verified replacement. |
| `runs/snapshots/` | 161 | 54,383,674 | Replace with the selected canonical snapshot generation. |
| `research/` | 1,624 | 738,048,127 | Not part of the product occupancy plan. Protect it in the approved backup before an authorized move or deletion. |
| Published forecasts, hindcasts and record | 2,621 | 199,731,464 | Retain. |

The final post-retention inventory on 19 September 2026 has two required occupancy measures:

| Measure | Objects | Bytes |
| --- | ---: | ---: |
| Total billable R2 occupancy | 28,943 | 2,316,739,847 |
| Product-only occupancy | 27,319 | 1,578,691,720 |

The difference is the separately protected `research/` archive: 1,624 objects and 738,048,127 bytes. It counts toward the R2 service allowance even though it is outside the product occupancy target. The measured research growth since the post-retention baseline is zero objects and zero bytes. Every projection on this page assumes zero research growth. New research data in these buckets invalidates that assumption and requires a capacity review.

The current product-only starting point is the measured 1.579 GB. It includes the existing raw and request history, the selected canonical catalog, one verified snapshot, four fit stores, all migrated typed issued results, the existing private hindcasts and the current public bucket. The exact cleanup removed superseded live run archives, canonical batches, snapshot generations and result generations.

## Recurring measurement

The frozen snapshot had 627 manifest batches and was 55,586,816 bytes. A later read-only catalog had 671 batches. Extending the snapshot through those 44 new batches took 17.49 seconds after the prior local snapshot was available. DuckDB made 332 `HEAD` and 83 `GET` requests and read 460,906 bytes. The catalog read was 1,102,712 bytes. Rewriting a compact local snapshot produced 56,373,248 bytes, an increase of 786,432 bytes. Appending into the old physical file instead increased it by 4,718,592 bytes, so the operation uses compact rewrite.

The same 44 batches referenced 33 new raw objects with 6,032,248 original bytes. Deterministic gzip produced 409,082 bytes, which is 6.78% of the original size. The measured delta contained fixture, injury, standings, FPL, Football-Data and Kalshi captures. It is a matchday-like busy delta, not an average day.

The four current cumulative result databases contain 59 issued forecasts and total 383,827,968 bytes. This is 6,505,559 bytes for each issued forecast at the current division mix. A lightweight revision points directly to one structural result and stores only effective market and display rows. All 59 current results are structural forecasts, so the measured average does not assume savings from lightweight revisions.

## Issued-detail inventory and table measurement

A read-only inventory on 19 September 2026 compared every public release index with its verified cumulative result pointer. It found all 59 issued results: 18 Premier League, 15 Championship, 15 League One and 11 League Two. Every released ID has a run, a public projection, valid lineage and non-empty match, stage-probability, score-grid, team-season and team-strength rows. No issued forecast has lost private detail.

The table-level measurement uses Championship result `2026-09-19T010319Z`, which has 468 matches and the largest division shape. Each table selection was written as lossless Zstd Parquet to measure compressed analytical payload by grain. These values are not direct DuckDB file allocations because DuckDB shares blocks and maintains indexes. The annual current-representation values allocate the observed 6.506 MB per issued result by the measured payload share. The base case has 1,460 issued results per year. The busy case has 1,580.

| Grain | Tables and representative rows | Lossless bytes | Payload share | Base annual current representation | Busy annual current representation |
| --- | --- | ---: | ---: | ---: | ---: |
| Run and provenance | `forecast_runs` 1 row, 184,739 bytes; `forecast_public_documents` 1 row, 42,710 bytes | 227,449 | 24.0% | 2.28 GB | 2.47 GB |
| Match and stage probabilities | `forecast_matches` 468 rows, 8,150 bytes; `forecast_match_probabilities` 947 rows, 37,351 bytes; names and unsettled fixtures 24 rows, 1,376 bytes | 46,877 | 4.9% | 0.47 GB | 0.51 GB |
| Score grids | `forecast_score_metadata` 936 rows, 59,018 bytes; `forecast_scores` 113,256 rows, 450,421 bytes | 509,439 | 53.7% | 5.10 GB | 5.52 GB |
| Personnel detail | Personnel columns from `forecast_matches`, 468 rows | 24,040 | 2.5% | 0.24 GB | 0.26 GB |
| Team strengths | `forecast_team_strengths`, 24 rows | 9,327 | 1.0% | 0.09 GB | 0.10 GB |
| Points and position distributions | `forecast_team_seasons` 24 rows, 22,624 bytes; `forecast_team_points` 1,739 rows, 6,874 bytes; `forecast_team_positions` 569 rows, 3,966 bytes | 33,464 | 3.5% | 0.34 GB | 0.36 GB |
| Events and conditionals | `forecast_team_events` 144 rows, 2,372 bytes; `forecast_conditionals` 4,752 rows, 90,683 bytes; impact metadata and fixtures 12 rows, 4,289 bytes | 97,344 | 10.3% | 0.98 GB | 1.06 GB |
| Total | 123,365 rows | 947,940 | 100% | 9.50 GB | 10.28 GB |

The score-grid row table is the largest representation. The next schema should keep one row for each result, match and score-generating stage, with the exact ordered `DOUBLE[]` values, both dimensions and the omitted probability. This is lossless: it keeps every stored floating-point value and can expand to the current analytical grain on query. Do not replace the grid with rates unless a separate validation proves that the retained parameters reproduce every stored cell exactly. The current grid table also has a primary-key index over 113,256 rows in this one result. A compact array removes those repeated keys and most index entries.

The run row also repeats large documents. In this result, `software_provenance` has 1,113,449 JSON characters. Its `live_snapshot` is 603,427 characters and its `data_manifest` is 502,254. A lossless compact design can store each immutable document once by content hash in the typed database and let each run reference that row. It must not drop the document or depend on a mutable pointer.

The representative lossless payload is 0.948 MB, compared with the observed 6.506 MB current-store average. At the same workload, this payload bound is 1.38 GB per base year and 1.50 GB per busy year. It is a design target, not a capacity commitment. A schema migration must verify byte-for-byte grid reconstruction, all 59 historical results and the complete analysis contract before it replaces the current representation.

The measured four-division 10,000-path calculation finished in 147.51 seconds after prepared inputs were available. The measured 44-batch local extension excludes the download of the prior snapshot and any remote upload. The live cutover verified snapshot, fit and result uploads and restores at current production size.

## Retention contract

| Data | Steady retention |
| --- | --- |
| Original provider evidence and request receipts | Indefinite. New original responses use lossless gzip and retain the hash of the original bytes. |
| Canonical observation history | One current verified snapshot plus the active canonical batches that collection still needs. Remove an unreferenced physical batch only after backup and reconciliation. |
| Snapshot generations | One pointed generation in steady state. Keep the prior object only through the pointer commit and smoke check. Report the two-file overlap as peak storage. |
| Fit state | One pointed cumulative database for each division. Its schema-declared checkpoints can contain more than one logical fitting boundary. |
| Private forecast detail | Indefinite for every issued prospective forecast. |
| Issued forecast projection and release receipt | Indefinite. One compact projection stays in the typed result database and one sanitized document stays on the public surface. |
| Result database generations | One pointed generation for each division in steady state. The prior immutable generation is a commit-time overlap, not permanent retention. |
| Hindcasts | Retain each released model edition until an explicit product-version disposition removes it. |
| Research and migration evidence | Store outside the steady product roots. Never delete it before the approved backup and disposition check. |

The production writer does not expire issued-result detail by age. Historical analysis reads the complete typed result. A compact public projection is a publication representation and is not a substitute for the private analytical grain. Any proposal to discard issued prospective facts is a separate product and data-retention decision that requires explicit approval.

`.github/workflows/retention.yml` runs a read-only exact-manifest plan each week. It records total billable occupancy, product-only occupancy, research growth, all deletion candidates and superseded snapshot, fit and result generations. It uploads the plan and a short report for 90 days. It fails as an operational alert when any reviewed-cleanup limit in `configs/retention.toml` is reached.

A reviewed cleanup is required at 5,000 candidate objects, 250 MB of candidates, eight superseded snapshot/fit/result objects, 5,000 net new objects, 6 GB of product occupancy, any research-byte growth, or 90 days since the baseline review. The workflow never deletes. An operator must review its exact plan and run `scripts/apply_r2_retention.py` separately. A cleanup can remove temporary objects and superseded physical generations. It cannot remove issued forecast facts. If issued-result growth causes the alert, the required action is a representation review. The first post-cutover dry run on 19 September 2026 found zero candidates, zero superseded generations and zero object or byte growth.

## Workload assumptions

| Input | Base case | Busy case |
| --- | ---: | ---: |
| Scheduled wakes | 8 per day | 8 per day |
| Matchday-like changed deltas | 4 per day | 8 per day on 60 days and 4 per day otherwise |
| Full issued forecasts | 4 per day | 6 per day on 60 days and 4 per day otherwise |
| Issued result detail | Indefinite | Indefinite |
| New hindcast editions | 1 per year | 1 per year |
| New research/backfill bytes in product buckets | 0 | 0 |
| New analyst cold starts | 30 per month | 300 per month |
| Retry allowance | Included in the operation estimate | 25% of request operations |

The base case treats four wakes as no-change or reusable-source wakes. The busy case applies the measured matchday-like delta at every wake for 60 days. Raw and canonical growth scales from the measured 44-batch delta. Typed issued-result growth uses the measured 6.506 MB current-store average. Public document growth uses the current public forecast average of about 0.289 MB. One new hindcast edition uses the current combined private and public edition size, about 0.35 GB. Research and one-off historical backfills are separate capacity events.

## Projection

| Case | Product start | Other product growth | Typed issued results | Public documents | Projected product occupancy | Research at zero growth | Projected billable occupancy |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 12-month base | 1.579 GB | 2.80 GB | 9.50 GB | 0.42 GB | 14.30 GB | 0.738 GB | 15.04 GB |
| 12-month busy | 1.579 GB | 3.21 GB | 10.28 GB | 0.46 GB | 15.53 GB | 0.738 GB | 16.26 GB |
| 24-month base sensitivity | 1.579 GB | 5.60 GB | 19.00 GB | 0.84 GB | 27.02 GB | 0.738 GB | 27.76 GB |
| 24-month busy sensitivity | 1.579 GB | 6.42 GB | 20.56 GB | 0.91 GB | 29.47 GB | 0.738 GB | 30.21 GB |

The current representation exceeds both the internal 7 GB product target and the 10 GB R2 allowance in the first year. At the modeled rate, the product reaches 6 GB in about four months. Representation work is therefore required before that alert. The lossless compressed-payload target would produce about 6.19 GB product and 6.92 GB billable occupancy in the base case, or 6.74 GB product and 7.48 GB billable occupancy in the busy case. Those target values require an implemented and verified compact schema; they are not current capacity.

One changed wake is projected at about 627 Class B and 209 Class A operations before forecast publication. This includes the measured 415 DuckDB source reads, snapshot and catalog reads, immutable-object existence checks and the measured 204 collection objects. Base usage is about 78,000 Class B and 26,000 Class A operations per month. The busy case with the retry allowance is about 112,000 Class B and 38,000 Class A operations per month. Fit, result, publication and analyst operations add less than 5,000 operations per month in this model. Both cases are below the internal and service limits.

At the end of the base year, a changed wake can download and upload a snapshot of about 1.2 GB. R2 egress is free, but time and runner disk are still constraints. The steady file plus commit-time overlap fits the current 14 GB runner disk model. A live remote restore, upload and clean-run bootstrap at projected size must pass before cutover and again before the nine-month review.

## Peaks and exclusions

The final two-bucket billable inventory is 2.32 GB before backup compression or versioning. Product-only occupancy is 1.579 GB. The projection assumes that the protected backup is outside the two steady product buckets. A backup copied into the same R2 product account must be added in full and would consume part of the headroom.

The final retention planner resolved 2,747 protected objects and listed 50,646 deletion candidates with 1,680,125,353 bytes. The candidate total contained 201,719,150 bytes of unreferenced canonical Parquet, 19,710,509 bytes of unselected manifests, 998,912,988 bytes of legacy forecast runs, 54,383,674 bytes of old run snapshots, 56,436,216 bytes of superseded canonical snapshots and 348,962,816 bytes of the four staged result generations. It listed all 1,624 `research/` objects and 738,048,127 bytes separately for review. The exact executor deleted all candidates in 51 requests and found zero survivors. The ignored evidence is at `runs/refactor/m4/final-retention-plan.json` and `runs/refactor/m4/final-retention-report.json`.

Each immutable pointer commit temporarily holds the old and new database. The projection reports only one steady generation. Migration can also hold the 3.07 GB old layout, the new 1.86 GB layout and the backup at the same time. That migration and recovery peak is separate from the steady target.

The current production inventory is measured, and the indefinite-detail model shows that the current representation does not pass the forward operating-capacity gate. Complete and verify the compact representation before product occupancy reaches 6 GB. The clean `main` runner collected evidence, extended and restored the snapshot, checked all four divisions and completed unchanged. A clean Pages run materialized and validated the complete public surface before deployment. Disaster recovery is not verified because no owner-confirmed bucket backup has been restored independently. A projected-size restore remains part of the compact-representation gate.
