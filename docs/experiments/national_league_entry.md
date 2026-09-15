# National League entry-source experiment

## Protocol

| Field | Value |
| --- | --- |
| Main base SHA | `f3660fe78367243290706acb406055ca422f559c` |
| Status | Pre-implementation protocol |
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
