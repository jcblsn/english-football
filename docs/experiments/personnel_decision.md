# Personnel batch 2: prospective validation and model decision

## Summary

| Field | Value |
| --- | --- |
| Branch | `research-personnel-measurement` |
| Batch 1 report | [personnel measurement](personnel_measurement.md) |
| Status | Decided on 15 September 2026: release v0.2 on retrospective evidence. The prospective archive continues as the post-release monitor. |
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

## 4. Release decision (15 September 2026)

The owner decided on 15 September 2026 to promote the matchday-squad continuity adjustment on retrospective evidence. The prospective gate of the steering memo was not run before this decision. No 2026/27 fixture from 17 September 2026 had been played.

| Question | Status at the decision |
| --- | --- |
| Mechanism | Retrospective support only. Realized D_squad improves every proper score in all 12 competition-seasons, with selection exposure because D_squad was chosen on the same seasons. |
| Measurement | Retrospective and development support. The history-only hindcast keeps 42% of the oracle gain. In the development week the D_a − D_h correlation is 0.84 at 3 days, 0.88 at 24 hours and 0.92 at 90 minutes. The injury and FPL part of the estimator and the 6-day horizon are not scored. |
| Product | Promoted without prospective evidence, with the rollback rule below and the prospective archive as a post-release monitor. |

### Freeze

- Freeze commit: `6fc7d818bc08f2c8fec0c836bdc87eb817dc1285`. GitHub `checks` run 35023567336 passed on it.
- The research archive for the prospective evaluation uses this commit. A later change to the estimator semantics must be recorded, with its commit, as a change to the released model.

### Rollback rule

This rule was written before any prospective outcome. It uses the same archive and evaluation as section 3.

- Review points: after the matches of 26 October 2026, then after the matches of 30 November 2026.
- Remove the adjustment from the structural forecast at a review point if either condition holds on prospective fixtures:
  - Measurement: at 24 hours, the correlation between estimated and realized D_a − D_h is below 0.5, or the sign agrees in less than 70% of fixtures with a realized absolute difference of at least 0.10.
  - Forecast value: at 90 minutes, the whole-round 95% interval of candidate minus control in score NLL is entirely above zero.
- Remove or correct the adjustment at once when an audited case shows a semantic or data error: a wrong club, a truncated squad, an identity split or an observation after the cutoff.
- A review that meets neither condition keeps the adjustment. It does not re-estimate κ or change the estimator.

The owner also decided that the release is a permanent change. A rollback, if a review point needs one, uses the Git history. The release keeps no parallel model track and no compatibility path.

## 5. Integration

The release is one pull request from `main` on the branch `personnel-squad-continuity`. It contains no research runner, report or parameter search.

```text
persistent M7 state
        +
temporary matchday-squad continuity adjustment
        ->
fixture structural rates
```

- `src/epl_forecast/personnel.py` holds the frozen specification of section 2 for the matchday squad only. The starting-XI estimator, both representation tables and the research κ for the starting XI are not in the product.
- The shift enters the match forecast and the season paths of the same fixture. The fitted filter, its likelihood and its sampled states do not change.
- The public model version is v0.2. The production fingerprint includes the personnel records of the fixtures in the horizon and the code of `personnel.py`, so a new squad, injury, FPL or team-sheet capture that changes a record makes a new forecast.
- Verification checks that each record is for a fixture in the horizon, that each team sheet was captured before the cutoff, and that each shift equals κ(D_a − D_h) with both clubs within the unresolved limit. The existing check that simulated frequencies agree with the published match probabilities also covers the shift.
- The public match document gives the discontinuity of each club and the home log-rate shift. It does not give player records.
- One rule is new in the product module: before any squad capture or FPL snapshot exists at a cutoff, a recent player without contrary dated evidence stays a member. This is the rule of the history-only hindcast (section 11 of the Batch 1 report). It cannot change a prospective snapshot, because squads and FPL were captured from 8 and 9 September 2026.

## 6. Season simulation

- Only a Premier League or Championship fixture that kicks off in the six days after the cutoff gets the shift. Six days is the longest checkpoint of the prospective protocol.
- A later fixture uses the persistent state only. The squad and availability evidence at a cutoff does not describe a fixture several weeks away, so the current personnel state is not carried through the season.
- The shift does not change the sampled team states, so it does not carry forward on a path. Playoff matches do not get it.
- Hindcasts use the same rule with history-only evidence: a matchday squad is known from the London day after its match and a transfer from its date. They use no injury lists, squad captures, FPL statuses or team sheets.
- The horizon rule was chosen before any prospective measurement. The prospective measurement at 6 days can support it or show that a shorter horizon is necessary. A change needs its own evidence.

## 7. Markets

- The shift enters the structural probabilities before market assistance. κ, q(m, n) and the availability values were not fitted to odds, and market prices do not enter the personnel evidence.
- The market-pool weight is 1.0, so the market-assisted probability does not change.
- The personnel contribution stays visible in the public document as the discontinuity of each club and the shift.

## 8. Operational findings

- Team sheets before kickoff are rare. 1 of 121 fixtures in 2026/27 before 15 September had one. Pull request #2 (collection every 9 minutes before kickoff) is open. Until it is merged, the observed D_squad is seldom available, and the 90-minute forecast mostly uses the expected D_squad.
- GitHub ran 4 scheduled production runs on 15 September 2026. Evidence at a cutoff can be older than its refresh interval.
- Bolton Wanderers, Cardiff City and Lincoln City have no adjustment until they have eight Championship matches with complete lineup minutes.
- API-Football publishes the injury list of a fixture only a short time before the match. At the release check on 15 September 2026 at 21:30 UTC, the latest injury captures covered Premier League fixtures up to 14 September and Championship fixtures up to 15 September. The 10 Premier League fixtures of 18–20 September had no API-Football availability evidence. Their availability came from FPL (406 available, 38 injured, 15 doubtful, 4 suspended and 1 unavailable), and their membership from squad captures, FPL clubs, transfers and matchday squads. 3 of 598 recent players had unknown membership. Early Championship adjustments have no availability evidence, because FPL covers only the Premier League.
- On the same check, the 10 Premier League shifts were between −0.054 and +0.081. The largest was Leeds United against Crystal Palace, where most of the absent Crystal Palace weight is departed players and members with availability 0.
- The validation page of the release branch records the production checks of v0.2. The Premier League forecast passed all 1,181 checks and the Championship forecast all 1,599. In the Championship, 9 of 12 fixtures in the horizon had a shift, from −0.068 to +0.032.

## 9. Post-release monitoring

- The research archive of section 3 continues for fixtures from 17 September 2026 with the freeze commit. It compares the released candidate with the structural M7 control and the realized-squad oracle.
- The review points and conditions of section 4 stay. At a review point, a failed condition is a reason to remove the adjustment with a new version.

## 10. Deliverable status

| Deliverable | Status |
| --- | --- |
| Frozen Batch 1 specification | Section 2 |
| Entry-step corrections and verification | Section 1. Freeze commit `6fc7d81`, GitHub checks passed. |
| Prospective measurement results | Not available at the decision. The first prospective fixtures are on 18 September 2026. |
| Prospective candidate, control and oracle results | Not available at the decision |
| Informative case audits | The evaluator writes `cases.csv`. 14 development snapshots were flagged. Prospective cases follow each archive run. |
| Operational findings | Section 8 |
| Season-simulation treatment | Section 6 |
| Release decision | Section 4: release on retrospective evidence, recorded as mechanism supported retrospectively, measurement supported in development only, product released without the prospective gate |
