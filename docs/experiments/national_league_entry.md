# National League entry-source experiment

## Protocol

| Field | Value |
| --- | --- |
| Main base SHA | `f3660fe78367243290706acb406055ca422f559c` |
| Status | Accepted for a focused production change; prospective confirmation required |
| Historical evidence label | Retrospective development evidence |
| Authoritative data | Private R2 bucket `page324-data`, read through a new empty workspace under `runs/` |
| Product control | M7 from the main base SHA, with a National League entrant treated as `outside -> eng-league-two` |
| Candidate | The same M7 with a complete prior National League season available to the generic entry-prior model as `eng-national-league -> eng-league-two` |

### Hypothesis and mechanism

A complete National League source season contains useful evidence about the initial League Two state of a promoted club. The candidate adds the National League only to the set of entry-source competitions. The League Two filter continues to update only from League Two matches. The existing transition regression estimates and shrinks the relationship between source strength and target strength. No coefficient is assigned by hand.

### Information cutoff

Only a source season that is complete and available before the League Two forecast cutoff is eligible. A National League result after a cutoff cannot affect that cutoff. Historical inputs come from R2, not from the repository `data/` directory. The current team identity registry is used verbatim and is extended only after review.

### Semantic and data checks

- Report season, team and match counts and source-season completeness.
- Verify aliases and identity continuity for each reconstructed promoted club.
- Verify that a prior National League season prevents an entrant from becoming `outside`.
- Withhold that season and verify that the previous fallback is recovered exactly.
- Change future National League results and verify that an earlier League Two forecast does not change.
- Verify that National League matches do not update League Two state.
- Verify that National League data cannot create a public forecast, ruleset, viewer competition or current pointer.

### Primary measurements

Use matched fixtures, origins, seeds and season-path counts. Compare cases pairwise.

- H/D/A log loss and score NLL over each entrant's first 10 League Two matches.
- Error in the first-10 realized Quality/Tilt proxy used by the entry-prior machinery.
- Complete-season entrant points and rank forecast scores.
- Promotion and relegation Brier scores when the event exists.
- Entrant calibration and uncertainty interval width.

Also report the normal whole-League-Two season panel as a collateral-effects check. Report source-conditioned entrants against the population fallback, strong against weak National League entrants, and new entrants against continuing League Two clubs. Do not tune on York City or Rochdale.

### Uncertainty

Use per-season effects and pooled matched differences. Use whole-season resampling for the season panel. If there are too few season clusters for a useful interval, show the individual season effects and describe uncertainty without a confident interval.

### Redirect or stop rule

If the first candidate does not improve the entrant slice, inspect source-strength estimation and transition shrinkage before making a claim about the information. Stop deployment if the semantic checks fail, if a credible corrected representation has no useful entrant signal, or if entrant gains do not survive proper scores and calibration without material collateral harm. A small whole-league average must not override the entrant-specific result.

### Retained evidence

The final artifact must record the base SHA, candidate SHA, R2 input manifest, configuration, cutoff convention, matched-case counts, primary results, important slices, limitations and reproduction command. Prospective 2026/27 control and candidate forecasts must remain archived before kickoff if the candidate reaches prospective operation.

## Result

The candidate passed the semantic checks. National League is not a product competition. National League matches do not update the League Two filter. A complete prior source season changes an entrant from `outside -> eng-league-two` to `eng-national-league -> eng-league-two`. Withholding the source restores the population fallback. A future National League result cannot change an earlier filter.

The R2 source audit covers 2010/11–2026/27. It found 14 complete source seasons, including the reviewed 23-team 2021/22 season. The 2019/20 season has 451 of 552 matches. The 2020/21 season has 477 of 506 matches. Both are retained but are not eligible as complete sources. The 2026/27 season is in progress. The registry review added 46 source aliases and preserved the Football-Data bytes. Older source files use Windows-1252.

On 180 first-10 entrant appearances in nine seasons, candidate minus control was −0.00296 H/D/A log loss, −0.00252 Brier and −0.00526 score NLL. Five of nine season effects favored the candidate on all three scores. The weak-source half had the larger pooled improvement, but this is a descriptive slice and not a tuning result. Across 5,960 League Two matches, changes were −0.00009 log loss, −0.00007 Brier and +0.00015 score NLL.

The first-10 realized attack/defence proxy did not improve in squared error: 0.08496 for the candidate and 0.08470 for the control across 32 dimension-level cases. Its Gaussian NLL improved from 0.21235 to 0.18883 while mean prior standard deviation increased from 0.12397 to 0.13208. The fitted source coefficient is strongly shrunk in early cohorts. The defence coefficient is positive in later cohorts; the attack coefficient changes sign before becoming positive. This is evidence for cautious source conditioning and against a hand-assigned transition coefficient.

In the 10,000-path season panel, the 16 source-conditioned entrant club-seasons improved at preseason by 0.00147 rank RPS and 0.175 points CRPS. The whole-season intervals include zero. The 90% points width increased by 0.44 points and coverage was unchanged. Promotion Brier improved by 0.00442 and relegation Brier worsened by 0.00082. At MW6, entrant rank RPS and points CRPS still improved. Later-origin results were mixed. Across all League Two clubs, preseason changes were +0.00036 rank RPS and +0.002 points CRPS, which are close to zero and slightly favor the control.

This historical result is development evidence, not fresh confirmation. It supports the approved structural correction because the candidate uses valid source evidence, passes the source-only invariants, improves all three first-10 match scores, and improves entrant preseason season scores without a material whole-league change. The mixed per-season and later-origin effects limit the claim. The 2026/27 prospective archive is the next confirmation sample.

## Retained artifacts

- Match evaluation: `research/evidence/national-league-entry/39bf554/match` in `page324-data`.
- Season control: `research/evidence/national-league-entry/28c0f5d/season-control` in `page324-data`.
- Season candidate: `research/evidence/national-league-entry/28c0f5d/season-candidate` in `page324-data`.
- Paired season report: `research/evidence/national-league-entry/0729098/season-report` in `page324-data`.

Reproduce the source acquisition and match evaluation with the research runners. Reproduce the season forecasts with `scripts/evaluate_seasons.py`, using `eng-league-one eng-league-two` for the control training set and adding `eng-national-league` for the candidate. Use the seasons, 10,000 simulations and seed recorded in the retained manifests.
