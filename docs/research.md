# Research history

The `main` branch holds only the supported product. The complete research history is on a separate branch. Nothing was deleted from Git history.

| Reference | Value |
| --- | --- |
| Branch | `research` |
| Tag | `research-anchor` |
| Commit | `f02a2fd` |

The tag marks the last commit before the product consolidation of 11 September 2026. At that commit you can find:

- The chronological experiment reports under `docs/experiments/`: E001, E002, the M4 to M10 studies, the season panels, and the entry-prior, market-pool and playoff-conditioning studies.
- The superseded models: M0, M1, the M3 Elo model, the M6 player model, the M8 process model, the M9 cross-division model and the M10 division map. That older M10 is a different model. The product M10 of `v0.3.0` uses the same name again.
- The player-layer research package `src/epl_forecast/research/`.
- One-off scripts: audits, diagnostics, parameter searches, previews and scouts.
- The pinned 2026/27 season projections of 10 September 2026, with their uncertainty sensitivity.
- The design notes and work plans: the north star, the architecture plan and the data migration plan.

Browse it online at [research-anchor](https://github.com/jcblsn/english-football/tree/research-anchor), or get it locally:

```sh
git fetch origin research --tags
git switch research
```

## Rules for new research

The `research` branch and the `research-anchor` tag are an archive. They are not the base for new work. Current `main` is the code and evaluation baseline.

1. For each workstream, make a new `research-<topic>` branch from current `main`. Git cannot keep a `research/<topic>` branch next to the `research` branch.
2. Before implementation, record the main base SHA, the hypothesis and mechanism, the structural comparator, the information cutoff, the primary metrics and slices, and the result that will stop or redirect the work. See [research principles](research_principles.md).
3. Port only the specific old code or ideas that the experiment needs. Keep experiment runners and artifacts out of the production path.
4. Compare each candidate with the current main M10 on matched fixtures, origins, seeds and path counts. Rebase on `main` while the experiment is active.
5. Measure a candidate with the checks in [validation](validation.md) and the [smoke tests](smoke_tests.md). Label historical results as retrospective development evidence. Archive matched prospective control and candidate forecasts when the mechanism depends on live information.
6. Move an accepted improvement to `main` as one focused pull request. Do not merge the whole `research` branch or an old research architecture into `main`.
