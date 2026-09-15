# Rolling personnel continuity mean effect

## Protocol

| Field | Value |
| --- | --- |
| Main base SHA | `080f7998f45da59ffebf73beb807d70cebef2d04` |
| Status | Oracle gate passed; prospective availability implementation under review |
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

## Oracle result

The current-main replay covers 8,388 Premier League and Championship matches in 2017/18–2025/26. Complete recent minutes and target starting XIs are available for 8,073. The chronological scored period has 5,450 matches in 2020/21–2025/26 and 12 competition-season clusters.

The corrected target map excludes substitute identities. Hand reconstruction agrees exactly for three semantic cases: Manchester United has D = 0.901 against Leicester on 11 May 2021, Leeds has D = 0.711 against West Bromwich Albion on 18 August 2023, and Chelsea has D = 0.520 against Fulham on 3 February 2023.

Kappa is stable and positive. It is 0.200 for the first scored season and then increases from 0.201 to 0.295. Every unconstrained fit has the same positive value as its constrained fit. No fit reaches a bound. The fixed 2026/27 coefficient fitted on all 8,073 pre-2026/27 matches is 0.26884.

Candidate minus control. Negative is better.

| Scope | Matches | H/D/A log loss | Brier | Score NLL | Team-goal NLL |
| --- | ---: | ---: | ---: | ---: | ---: |
| All | 5,450 | −0.00154 | −0.00107 | −0.00191 | −0.00096 |
| Premier League | 2,280 | −0.00254 | −0.00179 | −0.00183 | −0.00092 |
| Championship | 3,170 | −0.00082 | −0.00056 | −0.00197 | −0.00099 |
| Opening five | 577 | +0.00191 | +0.00139 | +0.00218 | +0.00110 |
| Promoted-club fixtures | 1,299 | −0.00280 | −0.00182 | −0.00236 | −0.00118 |
| Relegated-club fixtures | 763 | −0.00139 | −0.00100 | −0.00529 | −0.00266 |
| Absolute D difference at least 0.20 | 686 | −0.00787 | −0.00538 | −0.00951 | −0.00477 |

Score NLL improves in 10 of 12 competition-seasons. The Premier League loses by +0.00257 in 2020/21 and +0.00408 in 2025/26. H/D/A log loss improves in 8 of 12. Pooled 2025/26 score NLL is worse by +0.00127, and both competitions lose H/D/A log loss in that season. The whole-competition-season resampled score-NLL interval is [−0.00333, −0.00042]. With only 12 clusters and a hypothesis identified from these seasons, this interval is descriptive development evidence.

The classwise calibration error falls from 0.01439 to 0.01261. The median absolute log-rate shift is 0.021 and the maximum is 0.140. The adjustment changes almost nothing when the teams have similar continuity. It improves score NLL by 0.00951 on the prespecified D-imbalance slice of at least 0.20. The largest 5% of absolute case changes account for 68% of the total score-NLL gain. This concentration follows the mechanism, but it also makes the historical result fragile. The opening-five slice loses on every score.

### Oracle decision

This representation passes the oracle gate. The direction is stable, both competitions improve, all pooled proper scores improve and calibration does not degrade. The result supports a temporary relative Quality effect. It does not show that a pre-match availability feed can estimate realized starting-XI continuity.

Do not change M7 from this historical result. Proceed to a cutoff-safe prospective availability stage. The prospective record must decide deployment because the target starting XI is unavailable before kickoff and the hypothesis was identified from the same historical seasons used here.

## Prospective availability protocol

The first deployable stage uses the fixed eight-match window, the fixed temporary Quality mapping and one kappa fitted from all complete oracle seasons before 2026/27. It does not refit on prospective outcomes.

For each target fixture, use only provider observations captured before the archive cutoff:

- Use the latest complete API-Football squad capture for each team. A recent player outside that squad has availability zero. A squad capture with fewer than 18 identified players is insufficient, and D is missing.
- Use an API-Football injury row for the exact target fixture. `unavailable` gives probability zero and `doubtful` gives 0.5. An unknown status makes the player's availability missing.
- In the Premier League, use the latest FPL playing chance for the next round. If no numerical chance exists, `a` gives one, `d` gives 0.5 and `i`, `s` or `u` gives zero.
- When two positive observations for the same player and target disagree, mark the player's availability unknown and surface both observations. Do not select the more favorable value.
- A current squad member without contrary evidence has availability one. A newcomer has no recent-minute weight.

The first archive covers the next scheduled fixture of each Premier League and Championship team. It saves each player's recent weight, estimated availability, evidence basis and timestamp; team D; the control and candidate match distributions; and the later realized starting XI when it becomes available. Only a fixture archived before kickoff is a prospective case.

A material case has an absolute home-away D difference of at least 0.10 or a change of at least 0.05 from the prior archive. Keep nonmaterial cases as controls. Track missing teams, provider conflicts and false alarms. Do not tune the thresholds, probability mapping or kappa from named injuries.

## Reep identity investigation and first prospective archive

The first prospective run used code commit `d82b069` and cutoff `2026-09-15T15:06:12+00:00`. It produced 24 next-fixture records: 10 candidate forecasts and one material case. All 10 candidate forecasts were for the Championship. Every Premier League fixture had at least one missing D. This archive is an invalid implementation diagnostic. Do not score, upload or treat it as prospective evidence. The oracle result and fitted kappa are not affected because the historical oracle uses realized starting XIs and does not use FPL availability.

The failure was in team scoping. The runner indexed the latest FPL observation by player identity only. It then applied that observation while calculating D for any team in the player's recent history. A healthy player at his new club therefore supplied positive availability evidence to his former club. The captured squad excluded the player from the former club, so the runner returned missing availability instead of the required transferred-out value of zero. The run contained 34 such positive transfer-out observations across 14 former teams. Their combined recent weight was 0.9684 across the affected team-fixture calculations.

The audit also found 21 player-team cases in which the API-Football squad omitted a player but FPL assigned him to that same team. All 21 had zero FPL availability in this snapshot, so the numerical availability remained zero. The disagreements still show that a squad capture with at least 18 players is not necessarily a complete membership record. Preserve and report this condition.

### Reep validation

The investigation used the public Reep DuckDB release `20260907T201034Z`, generated on 7 September 2026. The downloaded file had the published size of 745,811,968 bytes and the verified SHA-256 `580eedc9dd633be820902b98cf7659794184d0702d366142e0751e74607bbfb5`. The release manifest is `https://data.reep.football/releases/20260907T201034Z/release.json`. Reep publishes this bridge register under CC0-1.0.

Reep has no bridge with provider name `fpl`. The retained FPL `fpl_code` field nevertheless maps through Reep's `opta/person_numeric` namespace. The two-hop audit used:

```text
FPL fpl_code -> Reep Opta person_numeric bridge -> Reep ID -> API-Football player bridge
```

| Current FPL identity check | Players |
| --- | ---: |
| Latest FPL rows | 659 |
| FPL codes found in `opta/person_numeric` | 635 |
| Rows with an onward API-Football player bridge | 543 |
| Exact agreement with the repository API player ID | 472 |
| Agreement after the reviewed API alias registry | 4 |
| Repository identity unresolved but Reep two-hop identity available | 67 |
| No complete FPL-to-API Reep path | 116 |

There were no unexplained disagreements among the 476 rows that both systems resolved after the four reviewed API aliases were applied. This is strong evidence that Reep can validate and extend the FPL-to-API identity mapping. Coverage is incomplete, so Reep cannot be the only resolver.

Reep does not solve team-at-time membership. The public register does not publish player squad or career relationships. Its `observed_clubs` table gives only a club count and first and last observed seasons, not the current club. The release is weekly and is suitable for stable identity bridges, not live transfer or availability decisions.

### Proposed infrastructure boundary

Treat identity resolution as a required semantic dependency of the personnel experiment. Do not make a broad player-ID migration as part of this work. The smallest proposed role is:

- Pin the latest Reep release published before the forecast cutoff. Retain its release stamp, manifest and checksum with the experiment inputs.
- Use Reep as an identity resolver and audit layer. Keep the repository's reviewed API alias normalization and an explicit unresolved fallback.
- Keep Reep ID and bridge provenance with each accepted FPL-to-API mapping. Resolve Reep redirects explicitly.
- Do not use Reep as current-squad evidence.
- Key availability evidence by player identity, target team and target fixture or round. Never apply a player's status at one club to another club.
- When FPL assigns a recent player to a different club, set his availability to zero for the former club. His playing probability at the new club is irrelevant to the former club.
- When FPL assigns a player to the target Premier League club, use the cutoff-safe FPL probability for that club and surface any disagreement with the API squad.
- When same-team providers give incompatible availability probabilities, return missing and retain both observations.
- When no valid FPL mapping exists, use cutoff-safe API squad and exact-fixture injury evidence. Do not use fuzzy matching silently.

Before a replacement archive is accepted, add invariants that a new-team FPL observation cannot increase availability for a former team, a transferred-out player contributes zero to the former team's continuity, the same identity can carry different team-specific availability at the same cutoff, and disabling Reep resolution preserves the reviewed fallback behavior. The eventual pull request must describe the failure, affected artifact, bridge coverage, unresolved cases, Reep release policy, team-at-time rules, chronology and fallbacks in sufficient detail for independent review.

## Retained artifacts

- Corrected current-main oracle forecasts: `research/evidence/personnel-mean/e82fd87/forecasts` in `page324-data`. Forecast code commit `058d062`.
- Corrected chronological report: `research/evidence/personnel-mean/e82fd87/report` in `page324-data`. Report code commit `e82fd87`.
- The earlier `research/evidence/personnel-mean/9f2203f` artifact is invalid and has an immutable `SUPERSEDED.json` marker. Its target map retained substitutes as zero-valued entries and then counted their identities as available. It measured matchday-squad continuity rather than starting-XI continuity. Do not use its results.

Reproduce with a new empty workspace:

```sh
uv run python scripts/research/personnel_mean.py predict --data runs/ws-personnel-mean --output runs/personnel-mean-forecasts
uv run python scripts/research/personnel_mean.py report --forecasts runs/personnel-mean-forecasts/oracle_forecasts.csv --output runs/personnel-mean-report
```

### Limitations

- The oracle uses realized starting XIs. It is not a forecast.
- The mean hypothesis was identified from the earlier pooled oracle on these seasons. The chronological mapping prevents target-season fitting but does not create a fresh confirmation sample.
- The scalar continuity measure assigns the same availability effect to every recent minute. It does not estimate player value.
- More than two thirds of the gain comes from the largest 5% of forecast changes, and 2025/26 does not improve in pooled score NLL.
- Historical lineups before 2026/27 cover only the Premier League and Championship.
