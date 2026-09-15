# Rolling personnel continuity mean effect

## Protocol

| Field | Value |
| --- | --- |
| Main base SHA | `080f7998f45da59ffebf73beb807d70cebef2d04` |
| Status | Active oracle representation test |
| Historical evidence label | Retrospective development evidence |
| Authoritative data | Private R2 bucket `page324-data`, read through a new empty workspace under `runs/` |
| Control | Frozen M7 from the main base SHA |
| Claim this experiment can update | Whether realized personnel continuity contains a temporary mean Quality signal that a small structural mapping can use |

### Hypothesis and mechanism

The stopped personnel-uncertainty oracle found a signed mean pattern instead of increased dispersion. A team with lower realized continuity scored fewer goals than M7 expected, and its opponent scored more. This experiment tests that separate information hypothesis.

For team i and target fixture f, D is one minus the share of minutes from the previous eight eligible matches represented in the realized target starting XI. The target XI is an oracle input. It removes substitutions, red cards and injuries during the target match from the feature.

The candidate applies one temporary Quality decrement per unit of D. With home and away discontinuity D_h and D_a:

```text
home log-rate shift = kappa * (D_a - D_h)
away log-rate shift = kappa * (D_h - D_a)
```

Kappa is one nonnegative coefficient shared by both competitions. Fit it by score likelihood within the fixed range 0 to 2. Also report the unconstrained fit from -2 to 2 as a direction check. A bound hit is a representation failure. This is the existing Quality geometry: lower continuity reduces the team's scoring rate and increases its opponent's scoring rate by the same amount. It does not update the persistent state, change Tilt or add variance. Kappa equal to zero exactly recovers M7.

### Structural comparator

The control and candidate use the same current-main M7 fits, fixtures, xG selection, entry priors, score law and predictive covariance. The candidate changes only the two log-rate means with the one-parameter Quality mapping above.

This representation differs from the rejected archived known-minutes roster bridge. That bridge mapped the difference between player shooting and creation traits in actual minutes and an eight-match average roster to own-team attack. Its diffuse trait contrast had almost no attainable in-sample gain. This experiment uses identity-preserving starting-XI continuity and the paired own-attack/opponent-attack signature found by the new oracle. It tests no player-value traits.

### Information cutoff and chronology

- M7 uses only observations eligible before the match day, with the product availability convention.
- Recent personnel weights use only matches before the target match date.
- Realized target starters are not available before kickoff. All results from this stage are oracle diagnostics, not deployable forecasts.
- Kappa is fitted once for each target season from complete earlier competition-seasons only. The first three eligible seasons form the initial estimation period. The target season is never used to fit its own coefficient.
- The hypothesis was identified from 2017/18–2025/26 oracle results. Chronological scoring on those seasons is still retrospective development evidence, not fresh confirmation.

### Population and primary measurements

The population is Premier League and Championship regular-season matches in 2017/18–2025/26 with complete starting lineups for both teams and a complete eight-match recent window. The primary scored period begins in 2020/21 after three full estimation seasons.

The primary comparison is the paired candidate-minus-control score NLL over all scored matches. Also report H/D/A log loss, Brier score, team-goal NLL and calibration. Use paired whole competition-seasons for uncertainty, and show every competition-season effect because 12 scored clusters do not justify a confident asymptotic claim.

Important prespecified slices are:

- Premier League and Championship separately;
- each target season;
- the opening five fixtures of each club's season;
- promoted and relegated clubs where the current evaluation data identify them;
- four prespecified bins of absolute continuity imbalance: less than 0.05, 0.05–0.10, 0.10–0.20 and at least 0.20;
- direction of the imbalance, to check that the adjustment moves the intended team rather than gaining through a pooled scoring-level correction.

Track the fitted kappa, its earlier-season support, applied log-rate shifts and whether the score change is concentrated in a small number of cases.

### Semantic checks

- Kappa equal to zero reproduces every control probability and score exactly.
- Swapping D_h and D_a negates both rate shifts.
- Equal continuity produces no adjustment.
- Changing a future lineup cannot change an earlier target's D or forecast.
- Increasing only one team's D lowers only its relative Quality for the fixture and does not change stored M7 state.

### Redirect or stop rule

Stop this representation if kappa is frequently zero or unstable in sign before the nonnegative constraint, if the pooled chronological score NLL does not improve, if the candidate loses in both competitions, or if any gain comes only from one narrow post hoc population. Do not build deployable availability from a failed oracle mapping.

If the oracle mapping improves score NLL with a stable direction and without material H/D/A or calibration harm, the next stage is a separately specified deployable test. It must calculate D from timestamped availability evidence and archive control, candidate and later realized lineups prospectively. Historical injury rows captured after the event cannot provide strict out-of-sample validation.
