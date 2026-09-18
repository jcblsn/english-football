# Instruction to the implementation agent

Use this as the opening task message after placing this directory at `refactor-handoff/` in the repository. This packet is a proposed assignment, not evidence that implementation, backup verification, or deployment has occurred.

---

Implement a substantial prelaunch refactor of `jcblsn/english-football`. Read `refactor-handoff/REFACTOR-BRIEF.md`, then inspect the current checkout and the relevant repository guidance and code. The September 18, 2026 audit used commit `a4da1cd7d433fd7d23ab074ac17d2207490b8ffb`. Treat its findings as a starting map, not an infallible description of your checkout or measured proof of a bottleneck.

Optimize for fewer concepts, less repeated work, lower retained storage and R2 request growth, faster forecasting, and faster analytical use. This is not a file-renaming exercise. Do not preserve obsolete interfaces, storage layouts, command flags, or compatibility readers merely because they existed. Preserve the product capabilities and scientific semantics described in the brief. Mathematical model changes require separate evidence; do not silently trade them for speed.

Start from one small application with a single durable-state writer, local execution against a verified input revision, explicit model inputs, reusable fit state, directly written analytical results, and a small public projection. A local DuckDB snapshot is the preferred first storage candidate. Test its transfer, local resource, retention, and recovery costs before committing the rest of the design to it. Choose the simplest alternative that meets the same requirements when measurements disqualify that candidate. Do not build both architectures permanently.

Work on a refactor branch or isolated worktree. Protect existing user changes. You may reorganize and replace implementation code, tests tied to obsolete representations, schemas, names, and the implementation-specific parts of repository guidance. Keep scientific checks, reviewed identity/rules evidence, source-history semantics, and public/private separation. Explain any conflict with existing guidance instead of either obeying an obsolete architectural restriction blindly or ignoring it silently.

Your first implementation milestone is a tested end-to-end Championship forecast from frozen inputs through local verification, typed analytical results, and an unpublished public rendering. Include real eligible squad-continuity inputs and playoff behavior. Establish a small independent reference first. Keep storage and input interfaces applicable to the other divisions from the start. Expand to all four before declaring the new path usable. Do not stop after writing a plan or generic framework scaffolding.

Use the brief's milestone gates. Carry out ordinary implementation decisions without repeatedly seeking permission. Inspect evidence and choose a default where that resolves an ambiguity. Ask only for unresolved authority, a consequential product/scientific decision, or access necessary for a blocked action. Continue independent local work when remote access is unavailable; mark the affected integration and capacity gates unverified.

Production writes, workflow changes, bucket deletion, and cutover require the owner's applicable authorization and the brief's backup, restore, and correctness prerequisites. The owner intends to back up both buckets before cutover; do not invent confirmation that this has happened. Backups permit replacement of layouts and deletion of superseded objects after validation. They are not a reason to keep an unnecessary dual stack. Never expose credentials or move private evidence into public Git, Actions caches, or public artifacts.

Maintain only a short decision record in the brief and the current `REFACTOR-STATE.md`. Record commands actually run, results, evidence locations, unresolved issues, and the next concrete action. Keep generated/private evidence in an authorized ignored workspace. Update current documentation rather than appending competing versions of it.

At each milestone report: what works end to end, what was deleted or simplified, which invariants were tested, measured time/requests/bytes, and remaining work. Distinguish measured results from goals and projections. Passing existing tests alone is not completion. Do not claim that a proposed command was executed or that the free-tier plan is certified while its inputs remain unknown.

Begin by establishing the checkout/reference state, resolving the scope of permitted external actions, and reading the startup paths in the brief. Then build the reference tests and first working slice. The first slice is a checkpoint, not the final scope of the refactor.
