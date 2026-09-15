# Personnel batch 2: prospective validation and model decision

## Summary

| Field | Value |
| --- | --- |
| Branch | `research-personnel-measurement` |
| Batch 1 report | [personnel measurement](personnel_measurement.md) |
| Status | Entry step in progress |
| Authoritative data | Private R2 bucket `page324-data`, read through new empty workspaces under `runs/` |

This batch uses the frozen Batch 1 specification to decide whether the next `v0.*` structural model includes a temporary matchday-squad continuity adjustment. It is a prospective validation, not a new personnel search.

## 1. Entry step

The Batch 1 review found four bounded correctness issues. They were corrected before the prospective window. No change touches κ, the propensity tables, the availability values or the unresolved limit.

### Forecast semantics

- Reference matches at the cutoff. Before, the archive gave the estimator all club matches dated before the target date. A match between the cutoff and the target was in that list, but the cutoff-safe evidence correctly did not contain its appearances, so the eight-match window was incomplete and the estimate was missing. Now `reference_matches` keeps only club matches that kicked off before the cutoff. A 6-day forecast uses the last eight matches known at 6 days and updates after a midweek match. A test covers a Wednesday match between a 6-day cutoff and a Saturday target.
- Whole matchday squad on a team sheet. Before, any capture with 11 starters became the observed matchday squad. Now a capture must also have at least 7 substitutes. In the 4,128 final API-Football team sheets of Premier League and Championship fixtures in 2024/25–2026/27, the bench has 7 substitutes in 6, 8 in 49, 9 in 4,071 and 11 in 2. A capture with fewer than 7 substitutes therefore does not show a whole squad, and the feature stays expected. A test covers a partial capture and an earlier complete capture.

### Evaluation and reporting

These changes do not change any forecast.

- Matched horizons. Before, the evaluator dropped the club when it built the set of fixtures with all four horizons, so a fixture was admitted when only one club had all four estimates. Now both clubs must have all four.
- Whole-round resampling. The evaluator takes the API-Football round of each fixture from the latest retained fixture capture. A postponed fixture keeps its original round. Each paired difference has a 95% interval from 2,000 resamples of whole competition rounds, and each round is shown.
- The evaluator also gives the exposure to large imbalances, the forecast comparison on fixtures with a candidate at all four horizons, and `cases.csv`, the individual audit of large adjustments, large realized imbalances, false and missed large signals and opposite signs. A large adjustment is an absolute log-rate shift of at least 0.073, the 90th percentile of the chronological historical D_squad forecasts.

### Protocol hygiene

- Pull request #2 is open, and its latest checks passed. The Batch 1 report said in one place that it was closed. That text is corrected.
- The `checks` workflow now also runs on a push to a `research-*` branch, so the research head has a recorded GitHub check run.
