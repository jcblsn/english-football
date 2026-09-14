# Research history

The `main` branch holds only the supported product. The complete research history is on a separate branch. Nothing was deleted from Git history.

| Reference | Value |
| --- | --- |
| Branch | `research` |
| Tag | `research-anchor` |
| Commit | `f02a2fd` |

The tag marks the last commit before the product consolidation of 11 September 2026. At that commit you can find:

- The chronological experiment reports under `docs/experiments/`: E001, E002, the M4 to M10 studies, the season panels, and the entry-prior, market-pool and playoff-conditioning studies.
- The superseded models: M0, M1, the M3 Elo model, the M6 player model, the M8 process model, the M9 cross-division model and the M10 division map.
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

1. Do broad model research on the `research` branch or on a temporary branch.
2. Measure a candidate with the checks in [validation](validation.md).
3. Move an improvement to `main` as one focused pull request.
4. Do not merge the whole `research` branch into `main`.
