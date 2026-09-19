# Refactor state

Status: M0 through M3 pass for the local code path. M4 production migration and cutover are in progress. This file records observed state only.

## Assignment and authority

Owner-approved scope: On 2026-09-18, the owner granted blanket approval for breaking changes, production writes, workflow cutover and deletion. The owner stated that version control protects the code, the complete local directory is backed up, and both buckets are backed up.
Local branch/worktree: `refactor-start`; implementation checkpoints are pushed to the branch after each verified slice. The checkout was clean before implementation started.
Authorized remote access: Credentials for both private buckets are configured in the ignored `.env`. Production writes and exact-manifest deletion are authorized.
Production mutation/cutover/deletion authority: Recorded in the owner instruction on 2026-09-18. The production workflow was disabled before the first mutation and no run was active.
Verified backup and restore evidence: The owner confirmed backups for the complete local directory and both buckets. Backup identifiers and an independent restore test are not available in this workspace.

## Baselines

Audited commit: `a4da1cd7d433fd7d23ab074ac17d2207490b8ffb`.
Checkout drift from the audited commit: Only the six files in `refactor-handoff/` were added before implementation started.
Existing user changes: None. Ignored evidence and generated roots include `runs/`, `site/`, `.env`, and environment caches. They are not deletion candidates.
Frozen source revision and reference manifest: The canonical pointer revision is `cde4f4364b85f9e1d97b27f0cf00330fd9adbb723662fc48de9a61148c0f3602`. It has schema version 1, 627 manifests, 1,967 files, and a latest retrieval time of 2026-09-18T17:27:57.638815Z. The frozen Championship reference run is `2026-09-18T062337Z` at cutoff 2026-09-18T06:23:37.340555Z with 10,000 simulations.
Numerical environment: macOS, Python 3.12.7, DuckDB and all other packages from `uv.lock`; `OPENBLAS_NUM_THREADS=1` was used for the measured forecast runs.
Baseline checks: `unset VIRTUAL_ENV; scripts/verify.sh` passed on 2026-09-18. Ruff format and lint passed. Pytest passed 378 tests in 54.66 seconds.
Historical performance context: `reference/observed_runtimes.csv` is retained as audit evidence only. The fresh Championship 10,000-path forecast completed in 231.45 seconds. The 100-path offline smoke test completed in 83.04 seconds.

## Current milestone

M4 — migrate production, cut over the scheduled writer and apply the reviewed retention plan.

Completed evidence:

- The checkout, local-change state, configured credential names, ignored roots, and audit drift were inspected.
- The startup path from `pipeline.operate` through `Dataset`, forecast subprocesses, verification, publication, and analysis-session construction was traced.
- The current operation opens a dataset for fingerprints and starts one forecast subprocess for each due division. Each subprocess loads live state, historical data, and personnel data through separate dataset instances.
- One immutable local DuckDB snapshot now contains all canonical observation tables, internal metadata, per-table logical hashes, a logical data revision, and a whole-file receipt. Restore verifies the receipt and metadata before atomic replacement.
- Temporal snapshot tests cover corrections, empty and repeated receipts, reschedules, stable identifiers, provider conflicts, and corruption.
- The measured snapshot has logical revision `5a82b0e93c0c931fcd6d1b91590c627ef0ee3e2c32fe5c94a6bd4ccc7885c88a`, 55,586,816 bytes, and local file hash `c2c733f7bfbf5f46851c527007b53d4528591b9142a68378947fd70db6553b59`. Its one-time source read used 1,989 GET requests for 20,567,898 response bytes and 7,868 HEAD requests. The R2 client also used one pointer HEAD and one catalog GET for 1,042,817 bytes.
- The forecast command accepts a verified snapshot and uses one prepared reader for live state, history, xG observations, sanctions, and personnel adjustments. A run with unusable R2 credentials completed locally, which proves that the restored forecast path has no hidden R2 read.
- Typed forecast results now store run identity, match stages and probabilities, score grids, team-season projections, event probabilities, point and position distributions, strengths, and conditional projections in DuckDB. Writes are transactional and idempotent by content identity.
- The Championship result used the same input-manifest hash, model specification, and personnel inputs as the issued reference. Maximum absolute differences were 4.00e-11 for fit diagnostics, 5.39e-12 for team strengths, 1.63e-11 for match values, and 3.55e-15 for simulation values. No numeric difference exceeded 1e-9.
- Product verification passed 6,289 of 6,289 checks. The typed result opened in 13.61 ms. A representative 24-team joined query had a warm p50 of 0.814 ms and p95 of 1.079 ms over 100 runs.
- Schema-declared fit checkpoints store mixture weights, member means and covariances, team indexes, entry priors, appearances, diagnostics, model-relevant xG identity, and the ordered historical prefix. They contain no serialized Python object graph.
- Exact Championship checkpoint reuse reduced a 100-path local run from 45.50 seconds to 7.86 seconds. The forecast documents were byte-identical after removal of `generated_at`.
- Checkpoint tests prove exact reuse, correction and xG invalidation, ordinary later-day resume against a fresh fit, and fresh fitting when an append would split one daily observation batch. An unrelated source-revision change with identical model inputs reuses the fit.
- One concurrent four-division run used the same restored revision, invalid R2 credentials, and 10,000 simulations per division. It completed in 147.51 seconds wall time. Division process times were 110.53, 135.28, 147.51, and 143.58 seconds.
- All four product verifiers passed: 4,581 of 4,581 Premier League checks, 6,289 of 6,289 Championship checks, 6,394 of 6,394 League One checks, and 6,399 of 6,399 League Two checks.
- Comparisons with all four issued private forecasts used each issued cutoff and ignored only `generated_at`. Maximum numeric differences were 3.64e-11, 4.00e-11, 7.28e-12, and 4.73e-11. No numeric difference exceeded 1e-9. League One and League Two had no nonnumeric differences. Premier League and Championship differed only in three wall-clock-dependent `next_match_for_teams` list positions each.
- The operation path now restores one immutable snapshot when its conditional pointer matches the canonical source revision. Otherwise, it builds one snapshot, uploads the database and manifest as immutable objects, and updates the pointer conditionally after both uploads.
- Four bounded workers now forecast and verify divisions concurrently from the same read-only snapshot. Each worker writes one typed result and uses one division-specific fit store. A verified fit store is uploaded immutably before its conditional pointer changes.
- Recovery tests prove that an interrupted snapshot pointer write leaves the prior pointer unchanged, a competing snapshot writer restores the complete winning revision, stale fit writers cannot overwrite a pointer, and restored fit bytes must match the recorded size and hash.
- Fit identity now includes a hash of model, training, schema, and normalization code. Resume tests cover later-day batches, a season boundary, training-window removal, historical correction, changed xG, late xG, and an incomplete same-day batch. Every tested resumed fit agrees with a fresh fit at 1e-11 absolute tolerance.
- Typed result schema version 2 now contains all public projection inputs at declared run, match, stage, score, team-season, event, distribution, conditional, and impact grains. The operation derives public forecasts from this database instead of reading private forecast JSON.
- The real Championship typed result contains 469 matches, 113,498 score cells, 24 teams, 144 team events, 1,753 point rows, 572 position rows, and 5,184 conditional rows. Its derived public document is exactly equal to the existing 15-match, 24-team, 12-impact-fixture document.
- Bulk score insertion reduced the measured real typed-result write and public round-trip from about 69 seconds to 9.45 seconds. The database is 11,546,624 bytes.
- Each division now restores one cumulative result database and commits its new immutable generation through a conditional pointer before public release. The append path does not list retained result objects.
- Publication now writes an immutable release receipt after the public forecast object. Prospective scoring uses the receipt's `released_at` value and excludes a forecast that completed before kickoff but was released after kickoff.
- Record-only changes set `public_changed`, and the production workflow deploys on that output instead of forecast count. A repeated idle wake with the same outcomes does not request another deployment.
- A London-origin date is stored with each successful division release. A new local day makes the projection due even when the provider fingerprint is unchanged.
- Effective inputs now have separate fit, projection, market, display, and model identities. A fit, projection, model, or London-day change selects the full operation path. A market-only or display-only change clones the prior typed result and changes only the applicable typed rows.
- Direct tests prove that a display refresh preserves every tested structural and simulation table, and that a quote refresh preserves the complete simulation and score grids. Clone writes are transactional, content-idempotent, and reject an existing ID with different content.
- An operation-level quote-only test restores and commits the cumulative typed result, publishes the new result, and fails if the forecast command is called.
- Typed result schema version 3 retains complete run provenance and the detailed personnel, market-stage, team-season, simulation, and forecast metadata that the analytical catalog exposes. Public output still comes through its explicit allowlist projection.
- Live analysis now resolves released IDs from the compact competition archives and reads them from one cumulative typed result database per applicable division. It does not fetch public forecast documents or the former private `forecast.json` and `run.json` objects.
- A selected analysis scope is available through `forecast_ids=`, repeated `--forecast-id` options in the data commands, and the query helper. A test with more than 250 unrelated retained archive pointers reads one result database and no unrelated forecast object.
- Analysis session identity includes the four typed result pointers and the selected forecast IDs. Existing hindcast version selection continues to bound retrospective editions.
- Pages materialization reuses an unchanged local hindcast tree by the hindcast index identity. The workflow restores that exact Actions cache, and a local repeat test reads no season series or weekly hindcast document.
- A changed append-only canonical catalog now extends the verified prior snapshot. A 44-batch live delta used 332 `HEAD` and 83 `GET` requests, read 460,906 canonical bytes, and completed the compact local rewrite in 17.49 seconds. The compact snapshot grew by 786,432 bytes; the rejected physical append grew by 4,718,592 bytes.
- New raw captures use deterministic gzip while their receipts retain the hash of the original provider bytes. The 33 raw objects in the measured delta fell from 6,032,248 bytes to 409,082 bytes. Existing uncompressed captures remain readable and replay verifies the decompressed original hash.
- Market-only and display-only result revisions now point directly to one structural result and store only effective market and display rows. Five measured Championship revisions grew a detailed result database to about 14.17 MB instead of 46.41 MB under row copying.
- Full private forecast detail has a tested 14-day window. Expiration requires a compact issued projection and protects the structural parent of a recent revision. Older result IDs remain available at public grain from the same cumulative typed database without a historical public-object read.
- A separate source-competition correction test rejects checkpoint reuse and proves that the replayed fit agrees with an independent fresh fit at 1e-11 tolerance.
- A read-only bucket inventory found 3,072,450,503 bytes. `runs/forecasts/` held 946,027,443 bytes, private hindcasts held 171,573,273 bytes, old run snapshots held 54,383,674 bytes, and `research/` held 738,048,127 bytes.
- The measured capacity model is in `docs/capacity.md`. The projected post-cutover product start is 1.86 GB. The 12-month base and 60-busy-day cases are 5.50 GB and 5.98 GB. The 24-month sensitivities exceed 7 GB and require a review at 6 GB or nine months. Projected monthly requests are about 78,000 Class B and 26,000 Class A in the base case, and 112,000 Class B and 38,000 Class A in the busy case.
- `docs/migration.md` defines the retention roots, deletion candidates, cutover prerequisites and bounded rollback. No production object was created, changed or deleted while collecting this evidence.
- The read-only retention planner protected 2,721 current objects and listed 50,591 exact deletion candidates totaling 1,221,840,776 bytes. It separated 1,624 `research/` objects totaling 738,048,127 bytes for owner review. The ignored plan is `runs/refactor/m4/retention-plan.json`; it made no mutation.
- Routine operation no longer uploads its temporary forecast renderings, logs or verification tree to `runs/forecasts/`. The typed result commits before public release, and a test proves that the legacy run prefix is not written.
- The production workflow was disabled before mutation. No production run was active.
- All 55 issued prospective forecasts that existed before cutover were reconciled against their private sources and public documents. The migration preserved every issued ID in four cumulative typed stores, preserved exact compact public projections and verified each available release receipt.
- The live snapshot uses canonical catalog digest `21bde6f3f604d523abc6a2c7270a2d333758c9e5447e8f790f36e38fd696479f`, logical data revision `0f4e30cecdbcf48e5fd81086811aa017fad94c02ed4a83fe709da5a7bf2a204b` and database digest `4287e9ef7258def55f6a9332082136fa05c340d4e6d7aef8f6034aaa9a538165`.
- The fixed-revision cutover operation created and verified the snapshot, ran all four 10,000-path forecasts, committed four fit stores and four result generations, and published run `2026-09-19T010319Z`. It completed successfully in 331.99 seconds with no division failure.
- The live public surface contains 59 prospective forecast IDs after cutover. All four current pointers name the cutover run and its release receipts. The prospective record has five scored matches.
- A fresh materialization validated every prospective document and archive. The retained hindcast path materialized 2,494 documents, and an unchanged repeat completed in three seconds through the local cache.
- The exact-manifest deletion executor requires the saved plan to match a fresh inventory and deletes only listed keys in bounded batches. Its tests cover stale-plan rejection, batching and remote deletion errors.

Selected first-slice design: Prove one immutable DuckDB snapshot that contains canonical typed observations, an explicit logical revision, and typed forecast results. Build it through one writer, checkpoint and close it before hashing or transfer, verify it before local replacement, and make calculations use local prepared inputs. Keep raw payloads separate. Do not create a second permanent storage backend.

Reason for this candidate: DuckDB is already pinned and used by the product. A local snapshot can remove repeated remote Parquet registration and archive reconstruction without changing M10. Realistic transfer, occupancy, retention, historical-cutoff, and recovery measurements can still disqualify the single-file unit before cutover.

## Capability disposition

| Capability | New owner or entry point | Required evidence | Old path disposition |
| --- | --- | --- | --- |
| Capture and reconcile evidence | One canonical snapshot writer after provider normalization | D1–D5 and migration reconciliation | Retain provider normalization first; replace manifest/Parquet reads after migration |
| Structural forecasts | Local prepared-input forecast service with explicit model specification and fit identity | N1–N4 for all four divisions | Remove forecast subprocess and repeated dataset construction after equivalence |
| Squad continuity and market assistance | Prepared fixture inputs with separate temporary and market stages | Real eligible Championship date and quote-only test | Preserve semantics; remove hidden dataset reads |
| Season projections | Existing M10 simulation behind typed inputs and results | N5–N6, including Championship playoffs | Preserve model and production simulation count |
| Publication and prospective record | Projection from authoritative typed result plus availability receipt | P1–P3 and recovery tests | Remove duplicate authoritative result formats |
| Analytical use | Views over the local snapshot and typed results | A1–A2 and query latency | Remove archive-wide JSON reconstruction |
| Evaluation, replay, and research | Explicit maintenance workflows over selected snapshot revisions | Consumer migration and retained-history checks | Keep capabilities; remove scheduled-path compatibility readers |

## Known limits and decisions

- The owner confirms that the private buckets and complete local directory are backed up. This workspace does not contain backup identifiers or evidence of an independent restore test.
- The capacity model uses a measured recurring 44-batch delta and the pre-cutover bucket inventory. Update it with the final post-retention inventory before M4 closes.
- The 12-month storage target depends on the reviewed cleanup and one steady physical generation per pointer. The current buckets still contain the superseded objects. The 24-month sensitivities exceed 7 GB.
- Public next-match selection depends on the projection time. The reconstructed public result had 15 available matches while the older issued artifact had 12. Private inputs and numerical outputs are the M1 equivalence evidence.
- The snapshot, fit and result pointer protocols now have a successful live cutover. Recovery tests still use isolated mock stores; the owner-confirmed bucket backups are the external rollback path.
- Historical hindcast generation remains an explicit maintenance workflow. Its analysis reader still uses the selected public hindcast edition because hindcast results have not moved into the live cumulative result database.
- Full live cutover and exact-manifest deletion are authorized. Correctness, reconciliation and capacity gates still apply before deletion.

## Restart point

Last successful full command and result: `scripts/verify.sh` passed format, lint, and all 420 tests in 49.08 seconds.
Next action: Fast-forward `main`, run the clean-runner workflow smoke check, generate the final retention plan and apply it.
Next test/gate: Final workflow, Pages deployment, post-deletion inventory and retained-history checks.
Working files to inspect before cutover: `docs/capacity.md`, `docs/migration.md`, the final pointer inventory and the backup evidence.
Remote objects created or modified by this agent: Four result-store generations and pointers for the legacy migration; one canonical snapshot database, manifest and pointer; four fit-store generations and pointers; four post-cutover result generations and pointers; public run `2026-09-19T010319Z`, its receipts, archives, current pointer and prospective record; operational forecast and impact state.
Temporary objects eligible for cleanup: `runs/refactor/m1/preflight-results.duckdb`, `runs/refactor/m1/offline-smoke-2/`, and the generated M2 cold, warm, all-four, and reference-rerun directories. They are ignored local evidence and have not been removed.

Update this file in place. Link to evidence without embedding raw data, logs, credentials, or the whole conversation.
