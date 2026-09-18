# English football: refactor execution brief

## 1. Status, purpose, and evidence

This is a proposed execution contract for a newly initialized repository agent. It supplies a destination, a working order, and tests. It does not prescribe every table, class, or module. No repository change, bucket mutation, new benchmark, backup verification, or deployment was performed to create this packet.

The prior audit examined `jcblsn/english-football` at `a4da1cd7d433fd7d23ab074ac17d2207490b8ffb` on September 18, 2026. It inspected source, repository metadata, an attached recursive local filename listing, and historical Actions logs. It did not run the project test suite or a fresh forecast and did not inspect private bucket inventories, account billing, or production query profiles. The included reference tables are historical evidence, not a fresh baseline.

The owner reported 3 GB in R2, 82,000 Class A operations, and 4.1 million Class B operations since a recent rollout. The operation measurement window and bootstrap/recurring split are unknown. The local filename listing does not establish file sizes, complete hidden-directory coverage, Git status, or backup completeness. Do not derive byte savings or recurring cost from those facts alone.

The original audit and charter are advisory inputs. The current code establishes current behavior, not necessarily correct behavior. Product intent and independently checked scientific invariants establish what must be preserved. Correct an audit claim when the evidence contradicts it. Record the discrepancy and keep working.

### Objective

Deliver the useful existing product with substantially fewer representations, less repeated I/O and computation, bounded storage overhead, and a straightforward operating model. Prefer deleting a mechanism to making it faster. Prefer an explicit local calculation to another remote service. Prefer removing an obsolete interface to maintaining its adapter indefinitely.

The priority order is: evidence integrity and scientific correctness; simpler architecture; free-tier headroom and reliable freshness; forecast/query performance; cosmetic organization. This order is not permission to neglect the lower priorities. Completion needs improvement across the agreed measurements, not a single flattering number.

Breaking internal APIs, storage keys, file layouts, command names, and prelaunch public schema versions is acceptable. Preserve capabilities, not incidental structure. Do not reduce simulation paths, history coverage, uncertainty, provider evidence, or analytical detail to manufacture an infrastructure speedup. Such tradeoffs must be identified as product or model changes and evaluated separately.

## 2. Capabilities that survive the refactor

Verify this inventory against the checkout. Add a discovered capability to the disposition map before removing its implementation.

| Capability | Required result | Initial source locations at the audited commit |
|---|---|---|
| Capture and reconcile evidence | Fixtures/results, reviewed identities, xG, appearances, squads, availability, transfers, odds, provenance, corrections, and meaningful empty captures remain usable | `data/capture.py`, `data/collect.py`, provider modules, `datasets.py`, `snapshots.py`, reviewed registries |
| Structural forecasts | The current M10 mathematical behavior and M2 reference can be fitted and compared; four divisions remain covered | `models/`, `training.py`, `cli.py`, `configs/product.toml` |
| Squad continuity and market assistance | Temporary squad adjustments and separately labeled market-assisted match probabilities remain distinct from persistent structural state | `personnel.py`, `market.py`, `live_forecast.py` |
| Season projections | Points/position distributions, division events, sanctions, ranking, playoff dependence, explicit European scenarios, and result conditionals remain correct | `simulation.py`, `postseason.py`, `sanctions.py` |
| Publication and prospective record | Public projections remain private-data-safe; issued probabilities and actual publication availability can be audited; record-only changes can be deployed | `publication.py`, `record.py`, `verification.py`, `site/`, workflows |
| Analytical use | Engineers can query current and historical evidence/results with declared grains, clocks, provenance, null semantics, and chosen retrospective versions | `analysis.py`, `analysis_artifacts.py`, `analysis_keys.py`, associated query consumers |
| Evaluation, replay, and research | Retrospective evaluation, replay, maintenance, and useful research/editorial consumers remain available through explicit workflows | `hindcast.py`, `match_hindcast.py`, evaluation modules, collection/audit commands, `charts/`, Datawrapper support |

All Python paths in the table are under `src/epl_forecast/` unless otherwise shown. National League evidence contributes to entry handling; it is not automatically a fifth public forecast product. Separate research collection from live invalidation, but do not silently remove its data or make it inaccessible to analysts.

Keep one small capability-disposition table during implementation: capability, new owner/entry point, relevant tests, and fate of old code/output. “No longer on the scheduled path” is not the same as “deleted capability.”

### Read in this order

First read `AGENTS.md`, `README.md`, the relevant product/operations/methodology/data/validation documents, `pyproject.toml`, and workflow definitions. Next trace `pipeline.py` into collection, `Dataset`, model construction, forecast export, verification, publication, and prospective scoring. Then trace one analytical query from session construction to its physical reads. Read numerical internals as the equivalence and checkpoint work requires them. Inspect tests beside each path.

Do not begin by reading every research artifact or every file in the 30,000-line local inventory. Use bounded reads and metadata summaries. Inspect the actual checkout's tracked, untracked, and ignored files separately. Preserve unrelated uncommitted work.

The audited `AGENTS.md` already prefers STE and a lean product line. It also embeds the current R2-reading architecture. Replace implementation-specific restrictions deliberately when adopting verified local snapshots. Preserve the underlying rule that local caches are not an independent authority. Do not relax the M10 scientific freeze merely to simplify implementation.

## 3. Authority and external state

The assignment message controls authorization. This template makes local branch implementation the default and does not itself authorize production mutation.

| Action | Default treatment |
|---|---|
| Local refactor, local tests, draft migration/cleanup tools, isolated worktree | Proceed when assigned implementation; protect user work |
| Read repository and available reference evidence | Proceed |
| Read private R2 or billing telemetry | Use only available authorized access; avoid repeated expensive inventories |
| Write isolated staging objects | Use only an explicitly designated, authorized bucket/prefix; keep them private |
| Disable workflows, change deployed pointers, migrate live buckets, delete live/local evidence | Use the owner's applicable authorization; first satisfy the objective gates below |
| Add a paid service or change scientific/product semantics | Surface the specific decision and evidence; do not infer approval from a general refactor request |

The owner intends both buckets to be backed up before refactoring their live contents. Before a destructive operation, identify the actual backup revision/location, establish its completeness for the affected objects, and demonstrate a restore. A backup must remain independent of the prefix being rewritten or deleted. Do not delete an unbacked local capture merely because both remote buckets were backed up.

Once explicit cutover/delete authority and these prerequisites exist, execute within that scope without requesting approval for each routine key or file. Do not turn operational caution into an indefinite ban on removing old layouts.

Never print `.env`, tokens, signed URLs, or credential values. Inspect configuration names and validate access without disclosing secrets. Do not place private input snapshots, restricted raw data, or sensitive run receipts in public Git, public artifacts, or public Actions caches.

## 4. Architecture to prove

### Default design

Use one application with a durable canonical relational history and one coordinating writer. Restore an immutable, verified revision to local storage for each operating job. Reuse authorized local copies when their revision is explicitly known. Pass prepared inputs to calculations. Write typed forecast results directly, then derive the public projection and analytical views.

A local DuckDB database distributed through private R2 snapshots is the first candidate. It is not a mandate to put raw bytes, every historical rendering, every checkpoint, and every forecast into one forever-growing physical file. Raw payloads stay separate evidence. Checkpoints are derived state. Public outputs are purpose-specific projections, not competing scientific truths.

Prototype whole-database restore/update/upload, local memory/disk use, historical reconstruction, and retained-copy overhead. If full-file movement or occupancy disqualifies this design, use the smallest measured refinement, such as stable table/season files plus a small current-state database. Select one design. Do not build a general storage-backend framework to avoid deciding.

Do not add a distributed scheduler, multi-service catalog, feature store, queue fleet, or lakehouse stack without a demonstrated requirement that the simpler design fails. Do not add an ORM just to express bulk SQL. Do not confuse fewer Python lines with less total system complexity.

### Responsibility boundaries

| Responsibility | Owns | Must not do |
|---|---|---|
| Collection/normalization | Provider calls, capture receipts, identity reconciliation, typed observations, source-specific errors | Invoke forecasting or publish raw evidence |
| Data preparation | Cutoff/revision selection and model/personnel/scenario inputs | Make hidden provider requests |
| Model and simulation | Numerical state, match distributions, season paths, result conditionals | Discover credentials, open R2, or select the latest data implicitly |
| Result storage and analytics | Declared-grain numerical results, queryable evidence and metadata | Reconstruct every past forecast from public JSON on each new result |
| Publication and scoring | Approved public projection, availability receipts, settlement, release decisions | Treat generated-at as proof of public availability |
| Orchestration | Clock, dependencies, bounded reads/writes, retries, stage decisions, telemetry | Become a second implementation of the numerical model |

These are responsibilities, not a requirement for six subpackages or six abstract interfaces. Start with ordinary modules and a small number of typed boundary records. Let implementation shape follow the resulting responsibilities.

### Snapshots and commit protocol

Use one owner for state commits. Numerical workers receive arrays/records or separate immutable read-only snapshots; they do not compete to write a shared live database. An analyst's independent snapshot should not block production updates.

The storage proof must show a consistent database snapshot, including the database's write-ahead state, not a casual copy of an actively changing file. Close/quiesce the writer and use the pinned engine's supported checkpoint/export behavior. Downloaded files are verified before use and replaced locally only when complete.

Write completed immutable objects before advancing a small authoritative pointer. Protect mutable pointer replacement with a precondition. Reject a stale writer's update. Treat an ambiguous network response as an unresolved operation to reconcile idempotently, not as permission to overwrite or publish twice. Verify behavior for the actual SDK, R2 API, and upload mode, including multipart when used.

An R2 pointer update and a Pages deployment are not one transaction. Define a small recovery state machine for prepared results, durable results, released public content, and the publication receipt. A crash at each boundary must preserve the last valid release or permit a safe retry. No release may refer to private results that were never committed. Do not claim atomicity across buckets, database files, and public deployment.

Retain a bounded number of full recovery snapshots. Count old, new, in-flight, backup, and analyst/distribution copies that live in R2. Do not keep one full database image per forecast forever. Preserve logical history and issued evidence independently of obsolete physical layouts.

## 5. Semantics before interfaces

### Clocks and evidence

Keep these meanings distinct wherever the product needs them: the event time; actual capture/observation time; assumed historical availability and its basis; the model's results cutoff; computation completion; and observed public availability.

Do not rewrite old captures to make them appear to have arrived earlier. Retrospective availability assumptions must remain labeled assumptions. Later corrections must not alter what a pinned historical revision says was known then. Historical analysis of what is known now and reconstruction of what was known then must be distinguishable operations.

Keep successful empty captures, failed requests, unknown values, and contradictory values distinct. A successful replacement of a squad or injury scope with zero rows can clear that scope. A failed response must not do so. Identical payload bytes captured twice may share storage while retaining both observation receipts when their timing matters.

A fixture keeps its identity when rescheduled. Reviewed identity registries and sanctions/rules evidence survive migration. Evidence concerning one team/competition/season does not silently replace another scope.

### Identities and invalidation

Separate logical data revision, model specification, fit-state identity, simulation settings, software provenance, and publication revision. A content identity is not a timestamp-shaped filename, and a software commit is not by itself a complete scientific model identity.

Changing physical packing must not change numerical input identity. Changing source availability, normalization semantics, parameters, relevant observations, or rules must invalidate the appropriate result. Unchanged values can still have freshness consequences. Compute narrowly scoped change information as data is ingested; do not replace remote scans with a full-corpus rehash on every no-change wake.

Use explicit dependencies and a small decision function, not a generic DAG execution framework. Test the decision, including its stated reason. The examples below hold other relevant inputs fixed:

| Change | Intended work |
|---|---|
| New result or relevant xG | Update affected fit state and applicable projections |
| Correction to historical result/xG or applicable entry evidence | Replay from a valid boundary; recompute affected descendants |
| Squad/availability change | Recompute temporary adjustments and projections that use them |
| Market quote only | Recompute market assistance and public match output; reuse unchanged structural work |
| Fixture date/status, sanction, or scenario change | Recompute the calendar/table/simulation/publication dependencies it actually affects |
| Display name or chart prose | Re-render; do not refit |
| Research-only evidence | Update its analytical domain; do not invalidate unrelated production state |
| New settled outcome with no new forecast | Update and deploy the public record |
| Clock advances without new provider data | Check cutoff transitions, latent-state evolution, kickoff eligibility, horizons, freshness, and scheduled work |

The last row is mandatory. “No new data” does not imply “no work due.” Reusing a filtered state is also not the same as publishing the same projection at a different origin. Test a clock-driven change and a genuinely idle wake separately.

## 6. Work sequence

Each milestone needs runnable evidence and a stated deletion/simplification result. Keep the old implementation as a pinned reference in a separate worktree or isolated environment, not as a permanent selectable production backend. Temporary comparison adapters have a removal condition.

### M0 — Establish a trustworthy reference and a bounded plan

Record current branch/commit and local changes; identify drift from the audit. Resolve actual access and mutation scope. Read the startup path and produce a concise capability/dependency/disposition map.

Select representative immutable source revisions and prepare a small reference suite spanning all four divisions. Freeze capture identities and configurations, not only an as-of timestamp. Obtain original normalized inputs and numerical outputs independently of the replacement normalizer. Two implementations reading the same incorrectly transformed inputs do not prove data equivalence.

Run the existing relevant checks in a controlled environment. Record pre-existing failures and investigate rather than deleting the failing checks. Lock the numerical environment for comparisons unless an environment change is an explicit part of the experiment. Add timing and physical request/byte counters at the relevant boundaries.

Exit evidence: reference manifest, representative baseline outputs, applicable tests, baseline measurements or explicit unavailable fields, and a short chosen first-slice design. Do not spend this milestone making a complete architectural encyclopedia or processing every archived experiment.

### M1 — Prove storage and one end-to-end slice

Build the candidate relational history, import a pinned input set, and test historical cutoff reconstruction, corrections, scope replacement, and restore. Benchmark the intended storage unit at realistic size, not only a tiny demonstration database. One bounded staging trial is preferable to repeatedly scanning the live bucket.

Run the Championship from prepared inputs through unchanged numerical behavior, season simulation including playoffs, verification, directly stored analytical rows, and an unpublished public rendering. Include a date for which the squad-continuity path genuinely applies. Also load another division through the same preparation contract to expose accidental single-league assumptions early.

Trace the operations. After restoring inputs, fitting, simulation, and archive verification must not open new remote datasets. Compare against the independent reference at both the input and output levels. Demonstrate a real analyst query over the new result.

Exit evidence: one working slice, storage candidate measured and selected, core temporal tests passing, and a clear list of old machinery this path replaces. Do not polish all providers or rename the whole package before this exists.

### M2 — Replace repeated work across the product

Move the other three divisions and required provider adapters onto the proven contracts. Read shared data once per operation. Reuse fit state only for an exact applicable specification, competition, input identity, and cutoff contract.

Persist schema-declared numerical checkpoints. Restore mixture weights, means, covariances, club indexes, required entry state, and evidence/protocol identity. Do not serialize opaque executable Python object graphs as the durable checkpoint contract. Include any sufficient historical inputs needed by the actual entry-prior and training-window semantics.

Test resumability rather than assuming the existing prefix mechanism is enough. Append in complete daily observation batches. Handle an old result correction, xG correction, late xG availability, normalization change, entry-evidence change, season boundary, and changing training-window membership. Resume before the earliest affected valid boundary or perform a fresh fit. Never silently use stale state.

Add stage-specific and clock-dependent invalidation. Preserve the current production simulation count for equivalence. Optimize the remaining measured numerical hotspots only after repeated I/O/refitting is removed. A ranking fast path must preserve ties and rules; future-date caching must respect entrants and time evolution. Change one numerical optimization at a time.

Exit evidence: all four divisions work; incremental-versus-fresh fits pass; genuinely unchanged fits are reused; quote-only and display-only changes avoid unrelated structural work.

### M3 — Complete outputs, analytics, retrospective work, and publication

Write declared-grain forecast facts directly. Keep a single authoritative numerical result, with public JSON and optional CSV/HTML derived from it. Multiple physical formats are acceptable when they serve a named consumer and have an explicit regeneration/retention rule. Do not enforce one-format purity at the expense of useful analysis.

Maintain analytical results incrementally. Provide selected current/historical/retrospective scopes without requiring every archive and model version. Preserve queryable detail, catalog meanings, provenance, and null semantics, even when table names change. Migrate the actual query/chart consumers and document new examples.

Process historical origins through reusable per-competition state where equivalence permits it. Keep retrospective products out of prospective scoring. Completed historical output should not be regenerated or redownloaded by every live deploy. A whole historical rebuild remains an explicit maintenance task.

Allow a verified league result to be released without waiting for unrelated leagues. Keep each league's origin, freshness, and status visible. Trigger deployment for changed record or other public content, not only a new forecast count. Cache immutable public documents appropriately and revalidate moving pointers.

Define prospective eligibility by the chosen public surface's observed availability, not computation completion. Retain immutable issue probabilities and an availability receipt. Do not invent exact historical publication times when the evidence is absent; label that limitation and keep uncertain legacy records out of claims requiring that proof. Distinguish all-product summaries from model-version and horizon cohorts.

Exit evidence: consumers migrated; no full archive reconstruction for one appended forecast; no full hindcast materialization for one live update; public privacy and record-only deployment tests pass; time-sensitive collection and publication have a measured freshness plan.

### M4 — Migrate, cut over, and delete the superseded system

Rehearse migration and restore from an identified backup. Reconcile row counts, declared keys, logical checksums, null categories, history intervals, provider coverage, and retained forecast/receipt identities. Equality of total row counts alone is insufficient. Compression or compaction must preserve capture and lineage resolution.

Under the owner's authorization, quiesce all relevant writers, account for captures that arrived during development, pin the final source revision, and complete the validated migration. Quiescing writers is not a reason to discard observations or silently create an unexplained capture gap. Test the selected release and checkpoint state before enabling the new schedule.

The cutover must have a bounded rollback plan. State which backup/code pair works together, how post-cutover captures would be preserved, and what symptom triggers rollback. Do not retain incompatible dual-writing implementations as a substitute for that plan.

Build an explicit deletion manifest from the actual retention roots and reviewed disposition map. Reclaim superseded physical generations only after retained history and issue receipts resolve without them. Protect the backup location, current release, checkpoints needed for recovery, retained raw evidence, and unique local captures. Delete old compatibility code and temporary migration/shadow paths after the successful cutover and agreed recovery window. Do not rewrite Git history by default.

Exit evidence: one production path; restored and verified backups; validated public release; old scheduled work disabled; approved objects/files reclaimed; operational docs describe the new system rather than old and new alternatives.

## 7. Acceptance tests

Assign each test an implementation location and a result. A test can be passed, failed, or unverified; a mock pass is not a live R2 integration pass. Numerical equivalence uses the same frozen evidence, configuration, and declared clock semantics unless a separately recorded correctness fix changes the expectation.

| ID | Scenario | Required assertion |
|---|---|---|
| D1 | Successful empty squad/injury scope, then failed fetch | Empty clears exactly its scope; failure does not erase it |
| D2 | Later corrected result/xG | Old pinned revision is unchanged; new revision uses the correction |
| D3 | Same payload at two capture times | Payload storage may be shared; meaningful receipts/timing are not lost |
| D4 | Provider disagreement, unresolved identity, missing value | Unknown/conflict/missing/empty distinctions and reviewed mappings survive |
| D5 | Rescheduled or undated fixture; sanction announced later | Fixture identity remains stable; only permitted cutoff evidence affects the result |
| N1 | Reference fit for all four divisions | Applicable moments, weights, rate distributions, and match probabilities agree within declared tolerances |
| N2 | Incremental fit vs fresh fit | Agree for ordinary appends, batches on the same day, season changes, and training-window changes |
| N3 | Historical correction and changed entry evidence | Invalid checkpoint rejected; valid replay or fresh fit matches reference |
| N4 | Late/corrected xG with unchanged results prefix | Results-prefix equality does not hide changed model inputs |
| N5 | Season uncertainty, playoffs, ties, European scenarios | Scientific dependence and rules remain correct; no independent-marginal substitution |
| N6 | Result conditionals | Same paths generate baseline and conditional values; partitions and weighted recovery remain valid |
| I1 | Truly idle wake | Bounded decision cost and no unrelated data loads or fit |
| I2 | Quote-only or display-only change | No structural refit/simulation when all other dependencies are fixed |
| I3 | Clock advances, data unchanged | Due cutoff/horizon/freshness/eligibility/state-evolution work is not skipped |
| A1 | One appended forecast, large retained archive | New result does not force enumeration and parsing of all historical forecast objects |
| A2 | Selected analysis scope | Correct historical/detail queries without eagerly rebuilding unrelated domains/versions |
| P1 | Compute before kickoff, release after kickoff | Not credited as publicly available before kickoff |
| P2 | Record changes, no new forecasts | Public deployment occurs and the record reflects the change |
| P3 | Public allowlist | No raw/licensed/private diagnostics or credentials leak through new schemas |
| R1 | Interrupted upload, pointer failure, ambiguous response | Last good revision remains valid; retries do not duplicate or overwrite issued results |
| R2 | Competing/stale writers | Commit conflict is handled; no lost update or mixed-revision release |
| R3 | Compaction and physical-generation deletion | Retained logical revisions and issue receipts still resolve |
| R4 | Backup restore and clean-machine bootstrap | Actual restored snapshot is usable and reproduces the specified reference |
| C1 | Representative steady and busy workloads | Measured requests, bytes, storage peaks, resources, and latency support the capacity plan |

Where coordinate systems change, compare equivalent transformed quantities, not raw array positions. Where random-number order changes, exact seed equality is not a sufficient equivalence claim. Compare deterministic layers separately; use declared multi-seed/Monte Carlo tests for season outputs and preserve dependence checks. Do not tune tolerances after seeing a failure merely to make it pass. Record intentional fixes separately from behavior-preserving changes.

Keep a small independent set of domain checks outside the shared calculation helper so that a bug in one helper is not “verified” by calling that same helper again.

## 8. Performance, growth, and freshness contract

These are initial engineering goals from the charter, not observed improvements or a promise that a specific design reaches them. Establish the baseline and benchmark workload first. Amend a target only with a visible reason and tradeoff, not by deleting hard cases from the workload.

| Measure | Initial target |
|---|---|
| Genuinely idle decision | Under 60 seconds end to end, with no full historical rebuild |
| Ordinary incremental four-division compute | Under 10 minutes after prepared inputs are available, using the production numerical settings |
| Warm, unchanged fitted state | Reused without replaying historical fitting |
| Representative warm local analytical SQL | p95 under 250 milliseconds on specified hardware/workloads |
| Appending a forecast | No enumeration/reparse of every prior live forecast |
| Live deployment | No reread/rematerialization of the full unchanged hindcast edition |
| One-year combined steady R2 occupancy | Below 7 GB as an internal headroom target; report migration/recovery peaks separately |
| Recurring monthly R2 requests | Below 5 million Class B and 250,000 Class A as initial internal budgets |

Report cold restore, fresh full fit, incremental fit, simulation, verification, upload, public deployment, and analyst startup separately. Also report the complete input-to-public path: it must not be hidden by the “inputs already available” compute target. A single query on an already-open database is not the same as a new analyst's time to first useful result.

Measure actual SDK/HTTP operations, including HEAD, GET/ranges, LIST, PUT, multipart work, and retries. DuckDB-originated requests need instrumentation too; wrapping only the Python store object can miss them. Record caller/stage and prefix class without secrets. Separate provider API requests from R2 operations and transferred bytes from net retained bytes. Keep instrumentation simple: structured events and summary files are sufficient unless another tool earns its cost.

Measure physical source bytes/files, tracked repository files, maintained adapters/schema variants, CLI surface, and rebuildable/retained output separately. Include generated code, dependencies, and operational configuration when judging system complexity. Do not achieve a Python-size target by moving the same complexity into generated SQL or configuration. Do not remove useful tests/comments to improve a count.

Produce a 12-month base and busy-case capacity projection, and preferably a 24-month sensitivity view. State collection frequencies, refresh events, new bytes by source, forecast retention, model versions, research/backfills, analyst cold starts, repeated whole-snapshot transfers, all retained snapshot copies, public reads if served from R2, retries, and backup/staging overhead. Use a measured recurring workload; separate one-time migration and historical backfill.

Useful accounting identities are:

`retained_bytes(t) = raw + canonical_history + retained_results + retained_checkpoints + all_snapshot_copies + backups + other_objects`

`peak_bytes = steady_bytes + concurrent_staging_and_recovery_overlap`

`monthly_requests = scheduled_work + matchday_work + analyst_work + publication_work + maintenance + retries`

All terms need units, a source, and an explicit assumption when not measured. Apply the actual service billing definitions. Recheck R2 allowances and the repository's Actions billing classification before certification. Do not use public-repository free compute as an excuse to accept stale publication. Do not treat the user's cumulative rollout counts as a recurring monthly rate.

Test scaling as well as today's size. Increase retained history in a private/local synthetic benchmark and assert that a fixed live update does not acquire a per-archive-object read loop. This does not mean a whole database restore has constant byte cost: measure its growth and revisit the physical split when it threatens the budget.

Set the matchday freshness objective explicitly. A short provider cache TTL does not prove that a workflow wakes, completes, and publishes at that cadence. Include late starts, provider failures, kickoff timing, and independent league failure. Do not promise strict pre-kickoff delivery from an unmeasured schedule.

## 9. Naming, style, and documentation

Choose one package name once: `football_forecast` for a general package or `page324` for the product. Do the mechanical rename after the new boundaries are proven, or together with the module replacement that removes the old boundary. Do not scatter aliases throughout production to cushion a prelaunch rename.

Use stable definitions for Competition, Season, Club, Fixture, Capture, ResultObservation, DataRevision, ModelSpec, FitState, Forecast, ForecastRun, Publication, and BacktestOrigin. These are a vocabulary, not instructions to create thirteen classes. Keep existing identifiers or provide an explicit migration map when changing them; display-label changes need not break identity.

M10 remains a research/provenance identifier; give the live model a descriptive name. Call the personnel feature squad continuity. Define tilt as scoring tendency. Call impact data result conditionals or conditional event probabilities, not causal effects. Keep clocks and model versions explicit in analytical grains.

Use STE principles, one term per concept, explicit input/output, and small typed boundary records. Comments explain why an invariant or numerical choice exists. Mathematical notation is welcome when defined and more precise than prose. Do not claim formal STE compliance without reviewing it. Do not hard-wrap ordinary Markdown prose merely to satisfy a code line limit.

Validate at trust boundaries and retain cheap scientific invariants at stage boundaries. “Validate once” is not permission to remove probability checks, lineage checks, or assertions protecting a numerical algorithm. Do not hide errors with broad defaulting or fallback to old schemas.

Replace old docs in place. Keep the current architecture/runbook and one small decision record. Preserve original issued numerical evidence but correct current explanations and label errata; do not preserve known-wrong current text for historical compatibility. Migrate old retained formats once, then remove their production readers. Keep old commits and a bounded rollback package, not a museum in `main`.

## 10. Working and completion protocol

Use one integration owner. Parallel agents, when available, may map consumers, author tests, review temporal semantics, or benchmark a defined component against frozen contracts. They should not concurrently redesign shared schemas or mutate the same buckets. A reviewer should examine the actual diff and test evidence, not merely agree with the implementer's report.

Maintain `REFACTOR-STATE.md` with the current commit, completed milestone evidence, pending decisions, actual remote revision/prefix information without secrets, and the next runnable action. Leave a clean restart point before a context reset. The state file is current state, not an append-only transcript.

For every milestone answer: What now works end to end? Which old concepts/files/paths disappeared? Which scientific tests passed? What was measured? What remains unverified? Where is the evidence? What is the next concrete action?

Do not stop at “tests pass” when the remote read loop, duplicate result formats, and compatibility stack remain. Conversely, do not claim complete verification when credentials or representative private inputs are missing. Finish independent local work and state the remaining external gate precisely.

Completion means one coherent implementation, migrated consumers, passing behavioral and recovery tests, measured improvement, a capacity model with known inputs, bounded retention, correct publication eligibility, and removal of superseded production paths. Full live cutover is complete only when it was authorized, performed, and observed successfully. A code-complete branch and a completed deployment are different deliverables.

## Reference material

The included `reference/` directory contains small historical evidence tables and their limitations. The larger original audit archive is optional background; do not commit generated private data merely to make the packet self-contained.

Official behavior references checked while preparing this handoff on September 18, 2026:

- DuckDB in-process concurrency: https://duckdb.org/docs/current/connect/concurrency
- DuckDB checkpoint semantics: https://www.duckdb.org/docs/current/sql/statements/checkpoint
- R2 S3 API compatibility and conditional operations: https://developers.cloudflare.com/r2/api/s3/api/

Verify behavior against the actual pinned software and service API used in the implementation. These references support the concurrency/snapshot/conditional-operation cautions; they do not validate this project's proposed performance targets.
