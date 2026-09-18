# Historical audit context

Source repository: `jcblsn/english-football`.
Audited commit: `a4da1cd7d433fd7d23ab074ac17d2207490b8ffb`.
Audit date: September 18, 2026.

This summary and the two CSV files are context from the prior audit. They are not new implementation-agent measurements. Inspect the current checkout and establish controlled before/after tests before claiming a speedup or a current defect.

`observed_runtimes.csv` records structured events from four historical GitHub Actions jobs. Each row contains source run/job URLs. Stage totals, operation totals, and workflow totals overlap; do not sum every row. They are not repeated runs on an identical frozen workload. Their commits predate the audited commit's Kalshi addition.

`tracked_source_sizes.csv` describes the 61 tracked files under `src/` at the audited tree, including 54 Python files totaling 747,806 bytes. Byte size is not line count, cyclomatic complexity, whole-repository size, or Git-history size. The two large analysis modules totaled 146,411 bytes. A reduction must be measured with consistent inclusion/exclusion rules.

The owner supplied 3 GB R2 occupancy, 82,000 Class A operations, and 4.1 million Class B operations after a recent rollout. The window and bootstrap/recurring split were not supplied. These are not evidence of a recurring monthly rate or a guaranteed future storage-growth rate.

The separate original recursive disk listing was parsed into 27,148 inferred non-directory entries, of which 25,154 were under `runs/`. It does not establish bytes, complete hidden-directory coverage, Git status, deduplication opportunity, or that local evidence has been uploaded and backed up. Do not use it as a deletion manifest. Inspect the actual filesystem carefully.

The prior audit inspected source, repository metadata, historical job logs, and the listing. It did not access bucket inventories, billing exports, private forecast payloads, or production query profiles. It did not run the test suite or a new local forecast. The refactor charter and this handoff describe proposals, not implemented changes.

## Starting hypotheses worth checking

- Repeated canonical-data/session setup is on the operational path.
- Live forecast subprocesses do not preserve the dynamic filter state across scheduled runs, despite incremental-fit support in the filter.
- Cold analytical artifact loading walks historical live forecasts and reconstructs tables from nested output documents.
- Live site materialization downloads historical hindcast content again.
- Physical compaction does not by itself reclaim all old stored objects.
- Publication eligibility and record-only deployment need explicit end-to-end tests.

Inspect code and run tests before treating any of these as a defect in a newer checkout. The previous source path map is in REFACTOR-BRIEF.md. A useful refactor removes the mechanisms that cause repeated work; it does not merely repeat the audit's labels.
