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

## 2. Frozen Batch 1 specification

| Item | Frozen value |
| --- | --- |
| Feature | D_squad = 1 − Σ_j w_j I(j in target matchday squad) / Σ_j w_j |
| Recent weights | Minutes, capped at 90, in the previous eight completed club matches. Each window match needs at least 700 recorded minutes. |
| Mapping | Δ = κ(D_a − D_h). +Δ on the home log rate and −Δ on the away log rate. Persistent M7 state does not change. |
| κ | 0.43161578781583126, fitted once on all 8,073 realized oracle matches before 2026/27 |
| Expected D_squad | Cutoff-safe membership, availability and matchday-squad propensity q(m, n), as in section 10 of the Batch 1 report |
| Availability | API-Football unavailable and FPL i, s, n or u give 0. Doubtful and FPL d give 0.3. FPL a and no contrary evidence give 1. Two providers that give 0 and 1 make the player unresolved. |
| Unresolved limit | No candidate when more than 25% of the recent weight of a club is unresolved |
| Observed D_squad | A team sheet captured before the cutoff with 11 starters and at least 7 substitutes |
| Starting-XI estimator | Diagnostic only, κ = 0.26883582806934564 |
| Control | Structural product M7, fitted from data retrieved before the London day of the cutoff. No market input. |

## 3. Prospective protocol

- Population: Premier League and Championship regular-season fixtures in 2026/27 that kick off from 17 September 2026 00:00 UTC.
- Checkpoints: 6 days, 3 days, 24 hours and 90 minutes before kickoff. No horizon is preferred before the evidence.
- Each snapshot is rebuilt from the observations retrieved by its cutoff with the freeze commit. Runs go to `research/evidence/personnel-measurement/<commit>/<run>/` in `page324-data`.
- Measurement comes first: bias, mean absolute error, correlation, sign behaviour, false and missed large signals, unresolved weight and revision, for club D_squad and for D_a − D_h against the final matchday squad. Horizons are compared on matched fixtures.
- Forecast value is separate: candidate minus control and realized-squad oracle minus control in score NLL, H/D/A log loss and Brier, by round, with whole-round resampling.
- The 2026/27 calendar gives Premier League round 5 and Championship round 8 on 18–20 September, then an international break. League play starts again on 9 October.
