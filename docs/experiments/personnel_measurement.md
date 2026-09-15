# Personnel measurement batch 1

## Summary

| Field | Value |
| --- | --- |
| Main base SHA | `080f7998f45da59ffebf73beb807d70cebef2d04` |
| Branch | `research-personnel-measurement` |
| Status | Measurement layer built. Prospective archive armed. Not a production proposal. |
| Evidence label | Historical results are retrospective development evidence. 2026/27 fixtures before 17 September 2026 are development cases. Fixtures from 17 September 2026 are prospective. |
| Authoritative data | Private R2 bucket `page324-data`, read through new empty workspaces under `runs/` |
| Frozen coefficient | κ = 0.26883582806934564, fitted on all 8,073 oracle matches before 2026/27 |

This batch does not change M7 and does not recommend a model change. It gives the evidence and the tools that Batch 2 needs to make a decision.

The two earlier reports are kept next to this report: [personnel uncertainty](personnel_uncertainty.md) (stopped) and [personnel mean](personnel_mean.md) (oracle gate passed, first prospective archive invalid).

## 1. Current-main reproduction

The oracle forecasts were made again at the main base with the ported code and a new empty workspace.

- All 8,388 Premier League and Championship matches in 2017/18–2025/26 agree exactly with the retained forecasts of commit `058d062`. The largest absolute difference in D, H/D/A probability, score log probability and team-goal NLL is 0.
- 8,073 matches have complete D for both teams.
- The chronological report agrees exactly with the retained report of commit `e82fd87`. The largest absolute difference over all 31 summary scopes is 0.
- The chronological κ values are 0.1999, 0.2009, 0.2292, 0.2542, 0.2783 and 0.2951. The all-history κ is 0.26883582806934564.

Candidate minus control on 5,450 chronologically scored matches in 2020/21–2025/26. Negative is better.

| Scope | Matches | H/D/A log loss | Brier | Score NLL |
| --- | ---: | ---: | ---: | ---: |
| All | 5,450 | −0.00154 | −0.00107 | −0.00191 |
| Premier League | 2,280 | −0.00254 | −0.00179 | −0.00183 |
| Championship | 3,170 | −0.00082 | −0.00056 | −0.00197 |
| Opening five | 577 | +0.00191 | +0.00139 | +0.00218 |
| Absolute D difference at least 0.20 | 686 | −0.00787 | −0.00538 | −0.00951 |
| 2025/26 | 907 | +0.00093 | +0.00088 | +0.00126 |

The season-clustered score-NLL interval is [−0.00333, −0.00042] with 12 clusters. The largest 5% of case changes give 68% of the gain.

The semantic checks agree with the documented protocol:

- The target is the starting XI. `lineup_minutes(..., starters=True)` keeps only rows with `starts`, and a starter counts as represented. A substitute or an unused player is not represented. A test covers this.
- The recent weights are the minutes, capped at 90, in the previous eight matches of the team with a match date before the target date. Each window match needs at least 700 recorded minutes, and the target needs 11 starters.
- M7 uses the product availability convention. κ for a target season uses only complete earlier seasons, after three initial seasons.
- κ = 0 gives a zero log-rate shift. The candidate probabilities and grid are then identical to the control. A test covers this.

The reproduction does not change the retained findings. It is still retrospective evidence on seasons that identified the hypothesis.

## 2. Roster-transition diagnostic

### Method

Each recent player who does not start the target fixture is put in one class. The classes use membership at the target date.

| Class | Rule |
| --- | --- |
| Departed | After the last matchday squad of the player for the club, and before the target, there is a transfer from the club without a later return, or a matchday squad of another club. |
| Benched | The player is in the matchday squad of the club for the target but does not start. |
| Retained | Not in the target matchday squad, not departed, and in a later matchday squad of the club in the same season. |
| Unresolved | None of the above. |

The four class weights add up exactly to D for every team-match. The report checks this for all 16,146 team-matches of the 8,073 complete matches.

This is a retrospective diagnostic. It uses later matchday squads and API-Football transfer records that were captured in September 2026. It is not a cutoff-safe feature.

Coverage and chronology:

- API-Football transfer records cover the club switches well. Of 2,491 changes of club between consecutive Premier League or Championship spells, 2,297 have a transfer from the earlier club, and 2,271 have a transfer dated between the two spells.
- Transfer dates are provider dates. Some are contract dates, not registration dates.
- Membership is decided only at dates, not at times.

### Where the discontinuity comes from

Mean team D and class weights by club match number:

| Division | Match number | Team-matches | D | Departed | Benched | Retained | Unresolved |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Premier League | 1–5 | 872 | 0.389 | 0.088 | 0.172 | 0.107 | 0.023 |
| Premier League | 6–10 | 884 | 0.316 | 0.025 | 0.173 | 0.111 | 0.006 |
| Premier League | 11–23 | 2,340 | 0.306 | 0.002 | 0.171 | 0.123 | 0.009 |
| Premier League | 24+ | 2,700 | 0.313 | 0.004 | 0.190 | 0.081 | 0.039 |
| Championship | 1–5 | 720 | 0.464 | 0.179 | 0.137 | 0.103 | 0.045 |
| Championship | 6–10 | 862 | 0.340 | 0.043 | 0.176 | 0.113 | 0.008 |
| Championship | 11–23 | 2,808 | 0.304 | 0.001 | 0.178 | 0.117 | 0.009 |
| Championship | 24+ | 4,960 | 0.318 | 0.009 | 0.179 | 0.095 | 0.035 |

The higher D in the opening five comes almost entirely from departures. The benched and retained weights do not change much with match number.

### Which part carries the signal

A diagnostic fit on all 8,073 matches replaces κ(D_a − D_h) with a separate coefficient for each class difference. The intervals resample 18 competition-seasons 300 times. These coefficients are for interpretation only.

| Class | Coefficient | 95% interval | Resamples above zero |
| --- | ---: | --- | ---: |
| Departed | 0.387 | [0.056, 0.731] | 99.7% |
| Benched | 0.065 | [−0.079, 0.208] | 79.3% |
| Retained | 0.395 | [0.305, 0.498] | 100% |
| Unresolved | 0.705 | [0.332, 0.998] | 100% |

A regular who is on the bench carries little of the signal. A regular who is not in the matchday squad carries most of it. The single κ averages these different effects.

### Opening five

With the chronological single κ, candidate minus control in score NLL for each class that has the largest absolute home-away difference:

| Scope | Largest difference | Matches | H/D/A log loss | Score NLL |
| --- | --- | ---: | ---: | ---: |
| Opening five | Departed | 215 | −0.00237 | −0.00595 |
| Opening five | Benched or retained | 298 | +0.00513 | +0.00842 |
| Opening five | Unresolved | 64 | +0.00130 | +0.00043 |
| After opening five | Departed | 246 | −0.00385 | −0.00556 |
| After opening five | Benched or retained | 3,846 | −0.00200 | −0.00186 |
| After opening five | Unresolved | 781 | −0.00110 | −0.00404 |

The permanent roster transition does not cause the opening-five loss. When departures cause the imbalance, the adjustment helps in the opening five and later. The loss comes from opening fixtures where the imbalance comes from players who stay at the club but do not start.

A chronological fit with separate departed, benched-or-retained and unresolved coefficients improves all matches from −0.00191 to −0.00236 score NLL, and 2025/26 from +0.00126 to +0.00052. It does not correct the opening five (+0.00207). A fit without opening-five matches, applied to the opening five, is worse with the separate coefficients (+0.00576) than with the single κ (+0.00445).

### Interpretation

The distinction makes the opening-season result partly intelligible. The failure is not permanent departure. It is the temporary-absence part of D at the start of a season, when the eight-match window reaches back into the previous season. A player who remains at the club but loses a starting place to a summer signing or a new manager is not a temporary departure from the current personnel regime. The previous-season reference then does not describe that regime. The data do not identify a demotion directly, so this explanation is a hypothesis.

Do not add a match-number switch. Do not add class coefficients from this diagnostic.

### Matchday-squad representation

The decomposition suggests a simpler latent quantity: how much of the recent personnel is in the target matchday squad, not who starts. One bounded comparison tests this with the same oracle data. No other player-state definition was tried.

- Starting-XI discontinuity D_xi is the recent minute share of players who do not start the target fixture. This is the retained feature.
- Matchday-squad discontinuity D_squad is the recent minute share of players who are not in the target matchday squad. It is D_xi minus the benched weight.

Each representation uses the same one-coefficient mapping κ(D_a − D_h) and the same chronological protocol as section 1. The home-away imbalances of the two representations have correlation 0.61. The all-history κ is 0.2688 for D_xi and 0.4317 for D_squad (grid fit).

Candidate minus control on the same 5,450 matches. Negative is better.

| Scope | Matches | D_xi H/D/A log loss | D_xi score NLL | D_squad H/D/A log loss | D_squad Brier | D_squad score NLL | D_squad − D_xi score NLL |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| All | 5,450 | −0.00154 | −0.00191 | −0.00266 | −0.00182 | −0.00365 | −0.00174 |
| Premier League | 2,280 | −0.00254 | −0.00183 | −0.00472 | −0.00320 | −0.00497 | −0.00314 |
| Championship | 3,170 | −0.00082 | −0.00197 | −0.00117 | −0.00082 | −0.00271 | −0.00074 |
| Opening five | 577 | +0.00191 | +0.00218 | −0.00100 | −0.00046 | −0.00126 | −0.00344 |
| After opening five | 4,873 | −0.00195 | −0.00239 | −0.00286 | −0.00198 | −0.00394 | −0.00154 |
| 2025/26 | 907 | +0.00093 | +0.00126 | −0.00155 | −0.00077 | −0.00261 | −0.00388 |
| Absolute D_xi difference below 0.05 | 1,646 | −0.00012 | −0.00011 | −0.00029 | −0.00008 | +0.00055 | +0.00066 |
| Absolute D_xi difference 0.10–0.20 | 1,691 | −0.00145 | −0.00224 | −0.00453 | −0.00317 | −0.00687 | −0.00464 |
| Absolute D_xi difference at least 0.20 | 686 | −0.00787 | −0.00951 | −0.00863 | −0.00609 | −0.01253 | −0.00302 |

Season-clustered 95% intervals with 12 competition-season clusters:

| Comparison | H/D/A log loss | Score NLL | Clusters below zero in score NLL |
| --- | --- | --- | ---: |
| D_xi − control | [−0.00280, −0.00045] | [−0.00328, −0.00038] | 10 |
| D_squad − control | [−0.00422, −0.00141] | [−0.00506, −0.00244] | 12 |
| D_squad − D_xi | [−0.00194, −0.00031] | [−0.00311, −0.00033] | 9 |

D_squad improves every proper score in all 12 competition-seasons. It has no opening-five loss and it improves 2025/26. The chronological κ for D_squad is 0.32, 0.33, 0.41, 0.43, 0.44 and 0.44. The largest 5% of case changes give 74% of its score-NLL gain, so the gain is still concentrated.

The matchday-squad representation captures the historical signal better than the starting-XI representation. It also needs an easier estimate: whether a recent player is available and selected for the matchday squad, not whether the player starts.

This comparison was chosen after the decomposition on the same seasons. It is retrospective development evidence and it is more exposed to selection than the retained D_xi result.

## 3. Data, identity and membership audit

### The invalid first archive

The archive of commit `d82b069` stays invalid and is not scored. Its runner indexed FPL availability by player identity only and applied it to every club in the recent history of the player. The semantics below replace that runner. The earlier module `research/availability.py` was not ported.

### Provider evidence in R2 on 15 September 2026

| Source | Semantics | Observed coverage and behaviour |
| --- | --- | --- |
| API-Football lineups | Starting XI and bench for one fixture. Team and fixture scoped. | 1 of 121 Premier League and Championship fixtures in 2026/27 had a starting XI captured before kickoff. Most lineups were first captured hours after the match. |
| API-Football squads | Squad list for one club at the retrieval time. | 44 clubs, 6 daily captures each from 8 September. 75 players left a squad between captures. None came back. 63 have a summer transfer from that club, and 34 are in the latest squad of another club. |
| API-Football transfers | Dated player moves. | Captured from 8 September. Loans and returns are separate rows. Some team IDs are not in the registry. |
| API-Football injuries | Unavailable or doubtful for one player, club and fixture. | Every mapped row names a club in its fixture. Before kickoff in 2026/27, 5 of 208 unavailable players and 7 of 74 doubtful players started. In the final historical records, 46 of 33,344 unavailable players and 36 of 5,092 doubtful players started. |
| FPL | Premier League club, status and chance of playing at the retrieval time. | 659 rows in the latest snapshot and 95 without a player identity. 504 FPL clubs agree with the latest API squad, 20 name another club and 40 players are in no API squad. Before kickoff, 0 of 118 i, s or u players started, and 1 of 15 d players started. |

A squad capture is not a complete membership record. In the latest captures, 344 of 1,462 players with Premier League or Championship minutes since 1 April 2026 are not in the squad of their club. Most of these are summer departures, but absence alone does not prove a transfer.

### Identity

- Canonical player IDs come from API-Football, with the reviewed alias registry. Lineups, minutes, squads, injuries and transfers use this identity.
- FPL rows get an identity at ingest from the FPL code registry, from name and birth date, or from club, birth date and name. The ingest does not keep which rule matched.
- Reep release `20260907T201034Z` checks the FPL identity through `FPL code → opta/person_numeric → Reep ID → api_football/player`. On the latest snapshot, 481 rows agree, 0 disagree, 83 have only a repository identity, 62 have only a Reep identity and 33 have neither.
- Only 12 of 437 players with minutes in the last eight matches of a current Premier League club have no FPL identity. They have 1.2% of the recent minutes, and Reep resolves 0.4%.

Reep is a useful audit of the FPL identity map. It does not change the continuity feature materially and it gives no club membership. Do not add it to production in this batch.

### Implemented semantics

`src/epl_forecast/research/personnel.py` keeps the three concepts separate. Every rule reads only rows with `retrieved_at` at or before the cutoff.

Fixture representation for the confirmed-XI arm:

- A player is represented only when the player is in the starting XI of the latest capture before kickoff that has 11 starters for that club.
- Substitutes are not represented. A capture at or after kickoff is not used.

Membership at the cutoff for a recent player and a club:

1. Strong evidence decides. A dated transfer from the club or a matchday squad of another club after the last appearance of the player for the club makes the player departed. A later transfer back to the club makes the player a member. The latest strong event wins, and weak evidence that disagrees is kept as a conflict.
2. Without strong evidence, the latest captured squads and the FPL club decide when they agree.
3. When they disagree, or when the only evidence is absence from the club squad, membership is unknown.

Availability for a member, a club and a fixture:

- API-Football unavailable gives 0 and doubtful gives 0.1. The rows must name the same club and fixture.
- In the Premier League, FPL i, s, n or u gives 0, d gives 0.1 and a gives 1. FPL is used only when FPL names the same club. An FPL row for another club can only be membership evidence against the former club.
- Two providers that give 0 and 1 make availability unknown. Otherwise the lower value is used. No evidence gives 1.

The value 0.1 for doubtful comes from the development captures before 17 September 2026. The FPL chance of playing is not a probability of starting, so it is not used.

Unknown membership or unknown availability makes the player unresolved. An unresolved player is left out of the expected D, and the recent weight of the player is reported. When more than 25% of the recent weight of a club is unresolved, the candidate is not made.

`tests/test_personnel_semantics.py` covers the batch invariants. An observation after the cutoff cannot change a feature. Substitutes do not enter confirmed-XI continuity, and the confirmed D equals the historical feature. A lineup captured after kickoff is not used. Identity is not membership. Availability is scoped to club and fixture. A new-club FPL status cannot restore a player to the former club. Unresolved players cannot create a large shock. Equal continuity gives zero adjustment. κ = 0 gives the control exactly. The adjustment does not change the fitted model. Odds in the store do not change the personnel evidence, and the control is the structural M7 specification.

## 4. Confirmed-XI prospective archive

### Collection

The prospective test needs official starting XIs that were captured before kickoff. On 15 September 2026, the store had such a capture for only 1 of 121 Premier League and Championship fixtures in 2026/27. The production workflow woke each hour, but GitHub ran only 4 scheduled runs on 15 September. Match details were due every 15 minutes from 90 minutes before kickoff.

Pull request [#2](https://github.com/jcblsn/english-football/pull/2) changes only collection. Production wakes every 10 minutes, match details are due every 9 minutes in the 75 minutes before kickoff and each hour during the match. M7 and the forecast fingerprint rules do not change. The pull request passed its checks but is not merged. Until it is merged, the confirmed-XI arm gets almost no eligible fixtures.

### Archive design

`scripts/research/personnel_prospective.py archive` makes three arms for each Premier League and Championship regular-season fixture in 2026/27:

| Arm | Personnel cutoff | Personnel input |
| --- | --- | --- |
| `confirmed-xi` | The later of the latest captures before kickoff with 11 starters for each club | Official starting XIs and recent minutes |
| `expected-24h` | 24 hours before kickoff | Expected-continuity estimator |
| `expected-90m` | 90 minutes before kickoff | Expected-continuity estimator |

Rules:

- A fixture enters the confirmed-XI arm only when both starting XIs were captured before kickoff. A lineup first captured at or after kickoff is never used.
- The confirmed D is the historical feature. The only difference is that the target XI comes from a capture before kickoff.
- The candidate uses the frozen κ = 0.26883582806934564. The runner never fits κ.
- The control is the structural product M7. It is fitted from data retrieved before the London day of the cutoff, with that day as the training cutoff. Control and candidate in one arm use the same fit. Market prices do not enter either forecast.
- Each record keeps the arm, kickoff, personnel cutoff, lineup retrieval times, M7 information cutoff, the latest squad, injury and FPL retrieval times, the eight reference matches and recent minutes of each club, the starters with identity provenance, home and away D, the log-rate shifts, and the control and candidate H/D/A probabilities, expected goals, 16×16 score grid and probability outside the grid.
- A fixture that kicks off from 17 September 2026 00:00 UTC is prospective. The code, the propensity table and κ were committed before the first such fixture. Earlier 2026/27 fixtures are development cases, and the doubtful mapping used their captures.
- Every provider row keeps its retrieval time, so the runner rebuilds each arm from the observations retrieved by its cutoff. The manifest records the archive time. An archive made after kickoff therefore uses the same inputs as an archive made at the cutoff, but it is not an observed forecast publication.
- `evaluate` scores finished fixtures, and compares each estimate with the realized starting-XI D. The realized D uses the same recent minutes as the archived arm.

Archives go to `research/evidence/personnel-measurement/<commit>/<run>/` in `page324-data`.

### Status on 15 September 2026

The first archive, `pm-archive-dev`, covers fixtures from 9 September 2026 to 18:53 UTC on 15 September 2026. It has 52 records and 46 candidates. All of them are development cases, and no prospective fixture has been played.

- Only Tottenham Hotspur against Everton on 12 September has a confirmed-XI record. Both XIs were captured 2 minutes before kickoff. The confirmed D is 0.583 for Tottenham and 0.381 for Everton. The XIs did not change after the capture.
- The two Championship fixtures at 18:45 UTC on 15 September have no confirmed-XI record.
- Bolton Wanderers, Cardiff City and Lincoln City have no D, because they have fewer than eight Championship matches with lineup minutes.

The valid prospective archive starts with the fixtures of 18 September 2026. Run the archive again after each match round, with a new empty workspace:

```sh
uv run python scripts/research/personnel_prospective.py archive --data runs/ws-personnel-archive --output runs/personnel-archive-<date> --since 2026-09-17T00:00:00+00:00 --upload
uv run python scripts/research/personnel_prospective.py evaluate --data runs/ws-personnel-evaluate --archive runs/personnel-archive-<date> --output runs/personnel-evaluate-<date>
```

The development archive and its evaluation are `research/evidence/personnel-measurement/0b98f57/pm-archive-dev` and `pm-eval-dev`. The reproduction, roster diagnostic and propensity runs are under `research/evidence/personnel-measurement/7a021aa/`. The invalid archive of commit `d82b069` is preserved, with an `INVALID.json` marker, under `research/evidence/personnel-mean/d82b069/invalid-prospective`.

## 5. Expected-continuity estimator

### Definition

For club i, target fixture f and cutoff c, with recent minutes w_j from the same eight-match window as the historical feature:

```text
E[D] = 1 − Σ w_j p_j / Σ w_j, over resolved players j
```

- p_j = 0 when the player is departed at the cutoff.
- p_j = a_j × s(k_j, l_j) when the player is a member. a_j is the availability from section 3. k_j is the number of starts in the eight window matches, and l_j shows whether the player started the last window match.
- The player is unresolved when membership or availability is unknown.
- A candidate is made only when both clubs have at most 25% unresolved recent weight.

Because the Quality correction is linear in D, E[D] enters the frozen mapping directly. The estimator does not predict a coherent XI. It has no formation, no player interactions, no player values and no constraint that the probabilities add up to 11.

### Start propensity

`scripts/research/start_propensity.py` estimated s(k, l) once from Premier League and Championship matches in 2021/22–2025/26. The population is players with minutes in the eight previous matches. Players listed by API-Football for the target fixture (19,643) and players with later evidence that they left the club (11,446) are excluded. The table is `src/epl_forecast/research/start_propensity.json`.

| Starts in last eight | Did not start last match | Started last match |
| ---: | ---: | ---: |
| 0 | 0.128 | — |
| 1 | 0.176 | 0.617 |
| 2 | 0.246 | 0.654 |
| 3 | 0.297 | 0.705 |
| 4 | 0.347 | 0.734 |
| 5 | 0.425 | 0.775 |
| 6 | 0.483 | 0.811 |
| 7 | 0.591 | 0.858 |
| 8 | — | 0.922 |

Each cell has at least 3,186 player-matches. The last start is strongly informative: a player with seven starts who did not start the last match starts next with probability 0.59, and with 0.86 if the player did.

The historical injury records are final provider records, not captures before kickoff. They are used only to remove listed players from this table.

### Coverage

In the development archive, the 90-minute arm has an estimate for 50 of 54 team-fixtures and the 24-hour arm for 44 of 48. Every missing estimate is a club without eight complete matches. The mean unresolved recent weight is 0.009 and the largest is 0.069. No club reached the 25% limit.

At 90 minutes, 1,060 recent players were members, 287 were departed and 29 had unknown membership. One departed player (0.3%) started. 15 of the 29 unknown players started, so unknown membership is not a hidden departure.

## 6. Expected versus realized continuity

These are development results. They use captures from before kickoff, but the doubtful mapping was chosen with the same fixtures and the code was written after the matches. The realized D uses the final starting XI and the archived recent minutes.

| Measure | 24 hours | 90 minutes |
| --- | ---: | ---: |
| Team estimates | 41 | 47 |
| Mean expected D / realized D | 0.441 / 0.416 | 0.442 / 0.414 |
| Bias in D | +0.025 | +0.029 |
| Mean absolute error in D | 0.061 | 0.060 |
| Correlation in D | 0.71 | 0.75 |
| Fixtures with both D | 20 | 23 |
| Mean absolute error in D_a − D_h | 0.075 | 0.071 |
| Correlation in D_a − D_h | 0.70 | 0.75 |
| Sign agreement when realized absolute D_a − D_h is at least 0.05 | 14 of 17 | 16 of 19 |
| Fixtures with realized absolute D_a − D_h at least 0.10 | 9 | 11 |
| Sign agreement on those fixtures | 8 of 9 | 10 of 11 |
| Estimate at least 0.10 but realized below 0.05 | 1 | 1 |
| Realized at least 0.10 but estimate below 0.05 | 2 | 2 |
| Players with a membership conflict | 35 | 39 |

The estimator is slightly too high in D. The bias is almost the same for both clubs, so it has little effect on the home-away difference. Player start probabilities are close to the observed rates at 90 minutes:

| Start probability | Players | Mean probability | Started |
| --- | ---: | ---: | ---: |
| 0.0–0.2 | 675 | 0.054 | 0.062 |
| 0.2–0.4 | 136 | 0.286 | 0.287 |
| 0.4–0.6 | 46 | 0.475 | 0.543 |
| 0.6–0.8 | 262 | 0.711 | 0.721 |
| 0.8–1.0 | 228 | 0.873 | 0.882 |

On these few development fixtures, the estimator follows the later XI feature well enough that a prospective forecast comparison is meaningful. It is not yet evidence that it does so prospectively. The sample is small and early in the season, when D is high because many recent players have left.

## 7. Early prospective forecast results

No prospective fixture has been played. The development results below are not evidence for the mechanism. The sample is too small, it is in the same week that set the doubtful mapping, and it is not prospective.

Candidate minus control. Negative is better.

| Arm | Division | Fixtures | H/D/A log loss | Brier | Score NLL |
| --- | --- | ---: | ---: | ---: | ---: |
| expected-24h | Premier League | 10 | −0.00063 | −0.00151 | +0.00514 |
| expected-24h | Championship | 10 | −0.02052 | −0.01483 | −0.02453 |
| expected-90m | Premier League | 10 | −0.00036 | −0.00113 | +0.00544 |
| expected-90m | Championship | 13 | −0.02074 | −0.01500 | −0.02211 |
| confirmed-xi | Premier League | 1 | −0.00457 | −0.00524 | −0.00447 |

Do not recommend production promotion from these results or from the historical reproduction.

## 8. Unresolved issues

Collection and operation:

- Pull request #2 is not merged. Without it, the confirmed-XI arm and the realized-versus-expected comparison stay very small.
- GitHub can delay or skip scheduled runs. A 10-minute schedule gives more chances, but it does not guarantee a capture in the hour before kickoff. If the capture rate stays low after the merge, a reliable external trigger for `workflow_dispatch` is the next option. It needs a token and a decision by the owner.
- The archive is rebuilt from retrieval times after the fixtures. No scheduled research job publishes it at the cutoff, because a scheduled workflow must be on `main`.
- The M7 control uses data retrieved before the London day of the cutoff, not all data retrieved before the personnel cutoff. This is the product match-day convention.

Measurement semantics:

- The doubtful value 0.1 comes from 89 development observations before 17 September 2026. The FPL chance of playing is not used, and FPL next-round and this-round fields are not mapped to fixtures.
- Transfer records have dates but no times. A transfer dated on the match day is treated as known on that day.
- Absence from a captured squad without other evidence stays unknown. The 25% unresolved-weight limit was set before the prospective results and was not tuned.
- The FPL ingest does not record which identity rule matched. Reep can audit the map but is not part of the pipeline.
- The start-propensity table is one pooled table. It is not different for division, club, season stage or manager change.
- A club promoted from League One has no lineup minutes before 2026/27, so it has no D until it has eight complete Championship matches.

Model interpretation:

- The historical κ mixes a weak benched effect and a stronger absent-from-squad effect. The confirmed-XI and expected arms both use the single frozen κ, so a prospective loss can come from this mixture as well as from measurement.
- The opening-season loss probably comes from a stale reference window after the summer, not from permanent departures. The data do not show demotions directly.
- The historical gain is concentrated in a few high-imbalance fixtures. A few prospective weeks cannot confirm or reject it.
