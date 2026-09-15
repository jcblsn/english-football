# Personnel measurement batch 1

## Summary

| Field | Value |
| --- | --- |
| Main base SHA | `080f7998f45da59ffebf73beb807d70cebef2d04` |
| Branch | `research-personnel-measurement` |
| Status | Measurement layer built. One estimator is archived at four horizons. Not a production proposal. |
| Evidence label | Historical results are retrospective development evidence. 2026/27 fixtures before 17 September 2026 are development cases. Fixtures from 17 September 2026 are prospective. |
| Authoritative data | Private R2 bucket `page324-data`, read through new empty workspaces under `runs/` |
| Frozen coefficients | κ = 0.26883582806934564 for starting-XI continuity and κ = 0.43161578781583126 for matchday-squad continuity, each fitted once on all 8,073 oracle matches before 2026/27 |

This batch does not change M7 and does not recommend a model change. It gives the evidence and the tools that Batch 2 needs to make a decision.

The product direction is one structural forecast that is updated continuously: the persistent M7 state plus the latest cutoff-safe expected personnel adjustment, whenever the forecast pipeline runs. The horizons in this report are evaluation checkpoints, not product variants. Section 9 gives the conclusions for Batch 2.

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

### Squad-native validation

This checks the frozen D_squad for semantic and data errors. It is not model selection. The run is `personnel_squad_audit.py` on the chronological D_squad forecasts of 2020/21–2025/26.

Candidate minus control by absolute home-away D_squad difference:

| Absolute D_squad difference | Matches | Mean absolute log-rate shift | H/D/A log loss | Brier | Score NLL |
| --- | ---: | ---: | ---: | ---: | ---: |
| below 0.05 | 1,963 | 0.010 | −0.00012 | −0.00009 | −0.00013 |
| 0.05–0.10 | 1,487 | 0.029 | −0.00085 | −0.00042 | −0.00050 |
| 0.10–0.20 | 1,597 | 0.055 | −0.00296 | −0.00195 | −0.00343 |
| 0.20–0.30 | 334 | 0.094 | −0.01703 | −0.01209 | −0.02256 |
| at least 0.30 | 69 | 0.139 | −0.03711 | −0.02819 | −0.08538 |

The absolute log-rate shift has median 0.029, 90th percentile 0.073, 99th percentile 0.129 and maximum 0.263. The improvement increases with the imbalance, and no bin is worse than the control.

Data checks:

- All 17,539 Premier League and Championship team-matches with a complete window have a target matchday squad of at least 16 players. 17,458 have at least 18. All 108 club sides in the top 1% of absolute shifts have at least 18. A missing bench therefore does not create the large adjustments.
- In the top 1% of shifts, departed players give on average 25% of the absent recent weight, against 10% over all team-matches.

Most of the 30 largest adjustments fall into three groups. All are absences in the provider records:

- Summer transitions. For example, Leeds United against West Bromwich Albion on 18 August 2023 after relegation (D_squad 0.68, 0.42 of it departed), and newly promoted Nottingham Forest in August 2022 after the loan players left.
- Late-season rotation. For example, Blackpool at Peterborough United on 7 May 2022, Luton Town against Hull City on 8 May 2023 before the playoffs, and Watford in May 2022 after relegation. These clubs had full matchday squads without their recent regulars.
- Injury and suspension clusters. For example, Tottenham Hotspur against Aston Villa on 26 November 2023, Newcastle United against Everton on 2 April 2024 and Southampton against Chelsea on 4 December 2024.
- The remaining cases, such as Blackburn Rovers twice in January 2026, have many absent regulars and almost no departed weight. The records do not show the reason.

No case shows a semantic failure: no truncated squad, no wrong club and no identity split. Late-season rotation is a genuine absence, but it is a different football situation from an injury crisis. The adjustment improved score NLL in 18 of the 30 cases, and a few large cases decide much of the gain.

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
| FPL | Premier League club, status and chance of playing at the retrieval time. | 659 rows in the latest snapshot and 95 without a player identity. 504 FPL clubs agree with the latest API squad, 20 name another club and 40 players are in no API squad. Before kickoff, 0 of 118 i, s or u players started, and 1 of 13 d players started. |

A squad capture is not a complete membership record. In the latest captures, 344 of 1,462 players with Premier League or Championship minutes since 1 April 2026 are not in the squad of their club. Most of these are summer departures, but absence alone does not prove a transfer.

### Identity

- Canonical player IDs come from API-Football, with the reviewed alias registry. Lineups, minutes, squads, injuries and transfers use this identity.
- FPL rows get an identity at ingest from the FPL code registry, from name and birth date, or from club, birth date and name. The ingest does not keep which rule matched.
- Reep release `20260907T201034Z` checks the FPL identity through `FPL code → opta/person_numeric → Reep ID → api_football/player`. On the latest snapshot, 481 rows agree, 0 disagree, 83 have only a repository identity, 62 have only a Reep identity and 33 have neither.
- Only 12 of 437 players with minutes in the last eight matches of a current Premier League club have no FPL identity. They have 1.2% of the recent minutes, and Reep resolves 0.4%.

Reep is a useful audit of the FPL identity map. It does not change the continuity feature materially and it gives no club membership. Do not add it to production in this batch.

### Implemented semantics

`src/epl_forecast/research/personnel.py` keeps the three concepts separate. Every rule reads only rows with `retrieved_at` at or before the cutoff.

Realized fixture representation, used only as an outcome label:

- For starting-XI continuity, a player is represented only when the player is in the final starting XI. Substitutes are not represented.
- For matchday-squad continuity, a player is represented when the player is in the final matchday squad, as a starter or a substitute.

Membership at the cutoff for a recent player and a club:

1. Strong evidence decides. A dated transfer from the club or a matchday squad of another club after the last appearance of the player for the club makes the player departed. A later transfer back to the club makes the player a member. The latest strong event wins, and weak evidence that disagrees is kept as a conflict.
2. Without strong evidence, the latest captured squads and the FPL club decide when they agree.
3. When they disagree, or when the only evidence is absence from the club squad, membership is unknown.

Availability for a member, a club and a fixture:

- API-Football unavailable gives 0. Doubtful gives 0.1 for a start and 0.3 for the matchday squad. The rows must name the same club and fixture.
- In the Premier League, FPL i, s, n or u gives 0, d gives the same doubtful value and a gives 1. FPL is used only when FPL names the same club. An FPL row for another club can only be membership evidence against the former club.
- Two providers that give 0 and 1 make availability unknown. Otherwise the lower value is used. No evidence gives 1.

The doubtful values come from the development captures before 17 September 2026: 8 of 87 doubtful players started and 25 of 87 were in the matchday squad. The FPL chance of playing is not a probability of starting, so it is not used.

Unknown membership or unknown availability makes the player unresolved. An unresolved player is left out of the expected D, and the recent weight of the player is reported. When more than 25% of the recent weight of a club is unresolved, the candidate is not made.

`tests/test_personnel_semantics.py` covers the batch invariants. An observation after the cutoff cannot change an estimate. Substitutes do not enter the starting-XI label, they do enter the matchday-squad label, and the starting-XI label equals the historical feature. Recent starts and matchday squads are counted separately. Identity is not membership. Availability is scoped to club and fixture. A new-club FPL status cannot restore a player to the former club. Unresolved players cannot create a large shock. Equal continuity gives zero adjustment. κ = 0 gives the control exactly. The adjustment does not change the fitted model. Odds in the store do not change the personnel evidence, and the control is the structural M7 specification.

## 4. One personnel-aware forecast observed at fixed horizons

### Product direction

The target is one structural forecast that is updated continuously: the persistent M7 state plus the latest cutoff-safe expected personnel adjustment. There is no separate pre-lineup product and no separate confirmed-XI product. The horizons below are research evaluation checkpoints of the same algorithm, not model identities.

### Collection decision

Official lineups are outcome labels for the research evaluation, and the existing captures after full time keep the final starting XI and matchday squad. No research arm depends on a capture before kickoff.

The official team sheet is still useful evidence when it is known before a forecast. When a capture before the cutoff has 11 starters for a club, the same estimator uses the captured matchday squad as the observed D_squad, with the same κ. This transition needs no separate model or product identity. `tests/test_personnel_semantics.py` covers it: a sheet captured before the cutoff makes the feature observed, and a sheet captured after the cutoff or at kickoff is not used.

Pull request [#2](https://github.com/jcblsn/english-football/pull/2) makes this capture operationally reasonable: production wakes every 10 minutes, and match details are due every 9 minutes in the 75 minutes before kickoff. It was closed on 15 September 2026 and reopened the same day, after the decision to capture team sheets before kickoff. It changes collection only and still needs owner review.

The oracle candidate in the evaluation applies the frozen coefficient to the realized label after the match. It separates mechanism error from measurement error and is never an operational forecast.

### Archive design

`scripts/research/personnel_prospective.py archive` runs the same estimator for each Premier League and Championship regular-season fixture in 2026/27 at four cutoffs: 6 days, 3 days, 24 hours and 90 minutes before kickoff. The grid was fixed before any horizon result and was not tuned. A snapshot is made only when its cutoff is on or after 9 September 2026, when all personnel sources were first captured.

Each snapshot keeps:

- the horizon, kickoff, personnel cutoff and M7 information cutoff;
- the latest squad, injury and FPL retrieval times;
- for each club, the eight reference matches and recent minutes;
- for each recent player, membership state, basis and conflicts, recent selection, availability for each representation, availability evidence and the probability for each representation;
- for each club and representation, the expected D and unresolved weight;
- the structural M7 control H/D/A probabilities, expected goals, 16×16 score grid, probability outside the grid and score-distribution parameters;
- for each representation, the frozen κ, the applied log-rate shift and the candidate forecast.

Rules:

- The control is the structural product M7, fitted from data retrieved before the London day of the cutoff. Market prices do not enter either forecast.
- Each representation has one κ fitted once on all 8,073 oracle matches before 2026/27: 0.26883582806934564 for D_xi and 0.43161578781583126 for D_squad. The runner never fits κ.
- A fixture that kicks off from 17 September 2026 00:00 UTC is prospective. The estimator, both propensity tables, both κ values and the horizon grid were committed before that time. Earlier 2026/27 fixtures are development cases, and the doubtful mapping used their captures.
- The runner rebuilds each snapshot from the observations retrieved by its cutoff. An archive made later uses the same inputs, but it is not a publication at the cutoff.
- `evaluate` attaches the realized labels to the same snapshots after the match. A label uses the eight matches before the target date and the final starting XI or matchday squad. It scores each snapshot, compares estimates between horizons and scores the oracle candidate.

Archives go to `research/evidence/personnel-measurement/<commit>/<run>/` in `page324-data`.

### Status on 15 September 2026

The archive `pm-archive-horizons` was made with commit `7dcb8ee`. It covers fixtures from 9 September 2026 whose 90-minute cutoff was before 19:31 UTC on 15 September 2026. It has 76 snapshots: 2 at 6 days, 23 at 3 days, 24 at 24 hours and 27 at 90 minutes. 57 snapshots have a candidate for each representation. All of them are development cases.

- A 6-day snapshot is possible only for fixtures from 15 September, because the personnel sources start on 9 September. The two 6-day fixtures were not finished at evaluation.
- Bolton Wanderers, Cardiff City and Lincoln City have no estimate, because they have fewer than eight Championship matches with lineup minutes.
- The runner includes a fixture only after its 90-minute cutoff. The first prospective fixtures are on 18 September 2026.

Run the archive again after each match round, with new empty workspaces:

```sh
uv run python scripts/research/personnel_prospective.py archive --data runs/ws-personnel-archive --output runs/personnel-archive-<date> --since 2026-09-17T00:00:00+00:00 --upload
uv run python scripts/research/personnel_prospective.py evaluate --data runs/ws-personnel-evaluate --archive runs/personnel-archive-<date> --output runs/personnel-evaluate-<date>
```

Retained artifacts in `page324-data` under `research/evidence/personnel-measurement/`:

| Key | Content |
| --- | --- |
| `7a021aa/pm-repro-forecasts`, `7a021aa/pm-repro-report` | Current-main reproduction |
| `7a021aa/pm-transition-features`, `7a021aa/pm-transition-report` | Roster-transition diagnostic |
| `3b27319/pm-representation` | Matchday-squad and starting-XI comparison |
| `3b27319/pm-propensity-v2` | Start and matchday-squad propensity tables |
| `7dcb8ee/pm-archive-horizons`, `7dcb8ee/pm-eval-horizons` | Development horizon archive and evaluation |
| `0b98f57/pm-archive-dev`, `0b98f57/pm-eval-dev` | Superseded development archive with the removed confirmed-XI arm |

The invalid archive of commit `d82b069` is preserved, with an `INVALID.json` marker, under `research/evidence/personnel-mean/d82b069/invalid-prospective`.

## 5. Expected-continuity estimator

### Definition

The estimator gives both representations from section 2. For club i, target fixture f and cutoff c, with recent minutes w_j from the same eight-match window as the historical feature:

```text
E[D] = 1 − Σ w_j p_j / Σ w_j, over resolved players j
```

- p_j = 0 when the player is departed at the cutoff.
- For D_xi, p_j = a_j × s(k_j, l_j) when the player is a member. a_j is the availability from section 3, with doubtful = 0.1. k_j is the number of starts in the eight window matches, and l_j shows whether the player started the last window match.
- For D_squad, p_j = a_j × q(m_j, n_j) when the player is a member. Here doubtful = 0.3, because 25 of 87 doubtful players were in the matchday squad before 17 September 2026. m_j is the number of window matchday squads with the player, and n_j shows whether the player was in the last one.
- The player is unresolved when membership or availability is unknown.
- A candidate is made only when both clubs have at most 25% unresolved recent weight.

Because the Quality correction is linear in D, E[D] enters the frozen mapping directly. The estimator does not predict a coherent XI. It has no formation, no player interactions, no player values and no constraint that the probabilities add up to 11.

### Start propensity

`scripts/research/start_propensity.py` estimated s(k, l) once from Premier League and Championship matches in 2021/22–2025/26. The population is players with minutes in the eight previous matches. Players listed by API-Football for the target fixture (19,643) and players with later evidence that they left the club (11,445) are excluded. The same run estimates q(m, n) from the same player-matches. The table is `src/epl_forecast/research/start_propensity.json`.

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

Matchday-squad propensity q(m, n):

| Squads in last eight | Not in last squad | In last squad |
| ---: | ---: | ---: |
| 1 | 0.297 | 0.917 |
| 2 | 0.345 | 0.911 |
| 3 | 0.397 | 0.909 |
| 4 | 0.402 | 0.907 |
| 5 | 0.474 | 0.914 |
| 6 | 0.522 | 0.924 |
| 7 | 0.628 | 0.939 |
| 8 | — | 0.959 |

Each cell has at least 1,657 player-matches. An available member who was in the last matchday squad is in the next one with probability 0.91–0.96, whatever the earlier selection. The squad quantity therefore depends mostly on membership and availability, and much less on selection.

The historical injury records are final provider records, not captures before kickoff. They are used only to remove listed players from these tables.

### Coverage

In the development horizon archive, the evaluation has an estimate and a label for 46 clubs at 90 minutes, 40 at 24 hours and 26 at 3 days. Every missing estimate is a club without eight complete matches. The mean unresolved recent weight is 0.009 at each horizon. No club reached the 25% limit.

At 90 minutes, 1,034 recent players were members, 281 were departed and 29 had unknown membership. One departed player (0.4%) was in the matchday squad and started. 22 of the 29 unknown players were in the matchday squad, so unknown membership is not a hidden departure.

## 6. Expected versus realized continuity by horizon

These are development results. They use observations retrieved before each cutoff, but the doubtful values were chosen with the same week and the code was written after the matches. A label uses the eight matches before the target date and the final starting XI or matchday squad. No 6-day snapshot has a finished fixture.

| Horizon | Representation | Clubs | Bias in D | Mean absolute error | Correlation | Fixtures | Mean absolute error in D_a − D_h | Correlation in D_a − D_h | Sign agreement, realized at least 0.05 | Sign agreement, realized at least 0.10 | Estimate at least 0.10, realized below 0.05 | Realized at least 0.10, estimate below 0.05 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 3 days | Matchday squad | 26 | −0.014 | 0.044 | 0.85 | 11 | 0.044 | 0.85 | 6 of 7 | 4 of 4 | 0 | 0 |
| 3 days | Starting XI | 26 | −0.000 | 0.053 | 0.70 | 11 | 0.070 | 0.61 | 7 of 8 | 4 of 4 | 0 | 2 |
| 24 hours | Matchday squad | 40 | +0.023 | 0.045 | 0.86 | 20 | 0.048 | 0.88 | 14 of 14 | 8 of 8 | 3 | 0 |
| 24 hours | Starting XI | 40 | +0.027 | 0.062 | 0.71 | 20 | 0.075 | 0.70 | 14 of 17 | 8 of 9 | 1 | 2 |
| 90 minutes | Matchday squad | 46 | +0.023 | 0.044 | 0.87 | 23 | 0.044 | 0.92 | 16 of 16 | 9 of 9 | 2 | 0 |
| 90 minutes | Starting XI | 46 | +0.030 | 0.060 | 0.76 | 23 | 0.071 | 0.75 | 16 of 19 | 10 of 11 | 1 | 2 |

Mean absolute change in club D between consecutive horizons:

| Change | Clubs | Matchday squad | Starting XI |
| --- | ---: | ---: | ---: |
| 6 days to 3 days | 0 | — | — |
| 3 days to 24 hours | 26 | 0.033 | 0.030 |
| 24 hours to 90 minutes | 40 | 0.005 | 0.004 |

Matchday-squad probabilities against the final matchday squad at 90 minutes:

| Probability | Players | Mean probability | In matchday squad |
| --- | ---: | ---: | ---: |
| 0.0–0.2 | 415 | 0.009 | 0.036 |
| 0.2–0.4 | 39 | 0.336 | 0.231 |
| 0.4–0.6 | 39 | 0.459 | 0.436 |
| 0.6–0.8 | 12 | 0.628 | 0.500 |
| 0.8–1.0 | 810 | 0.935 | 0.942 |

Start probabilities against the final starting XI at 90 minutes are 0.054 against 0.062, 0.287 against 0.290, 0.476 against 0.568, 0.711 against 0.722 and 0.873 against 0.879 in the same bins.

In this small sample, the matchday-squad feature is measured more accurately than the starting-XI feature at every scored horizon. The difference is largest for the home-away difference, which is the quantity the mapping uses. Most of the probability mass of the matchday-squad estimate is near 0 or near 1, so it depends mainly on membership and availability. The estimate changes most between 3 days and 24 hours and changes little in the last day. The 3-day sample has only 11 fixtures.

## 7. Forecast value by horizon

No prospective fixture has been played. These development results are not evidence for the mechanism or for a horizon. The oracle applies the same frozen κ to the realized label after the match. It separates mechanism error from measurement error and is never an operational forecast.

Candidate minus control and oracle minus control. Negative is better.

| Horizon | Representation | Fixtures | Candidate H/D/A log loss | Candidate Brier | Candidate score NLL | Oracle H/D/A log loss | Oracle score NLL |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 3 days | Matchday squad | 11 | +0.00427 | +0.00422 | +0.01985 | −0.00443 | +0.01136 |
| 3 days | Starting XI | 11 | +0.00308 | +0.00189 | +0.00373 | +0.00069 | +0.00108 |
| 24 hours | Matchday squad | 20 | −0.01383 | −0.01027 | +0.00079 | −0.01786 | −0.01613 |
| 24 hours | Starting XI | 20 | −0.01058 | −0.00817 | −0.00970 | −0.01057 | −0.02074 |
| 90 minutes | Matchday squad | 23 | −0.01864 | −0.01350 | −0.00319 | −0.01863 | −0.01582 |
| 90 minutes | Starting XI | 23 | −0.01188 | −0.00897 | −0.01013 | −0.01032 | −0.01893 |

The oracle with realized labels is also worse than the control in score NLL on the 11 three-day fixtures. The three-day loss is therefore not caused by measurement in this sample. With 11–23 fixtures, a few matches decide these values. Do not recommend production promotion from them or from the historical results.

## 8. Unresolved issues

Collection and operation:

- The archive is rebuilt from retrieval times after each round. No scheduled research job publishes snapshots at their cutoffs, because a scheduled workflow must be on `main`.
- GitHub ran only 4 scheduled production runs on 15 September 2026. Injury, squad and FPL evidence at a cutoff can therefore be older than its refresh interval. The snapshots record the retrieval times.
- Pull request #2 was closed. If a later diagnostic needs official XIs before kickoff, the collection question must be opened again.
- The M7 control uses data retrieved before the London day of the cutoff, not all data retrieved before the personnel cutoff. This is the product match-day convention.
- No 6-day snapshot is scored yet, and the 3-day sample is 11 fixtures. The horizon questions need several prospective rounds.

Measurement semantics:

- The doubtful values 0.1 and 0.3 come from 87 development observations before 17 September 2026. The FPL chance of playing is not used, and FPL next-round and this-round fields are not mapped to fixtures.
- Transfer records have dates but no times. A transfer dated on the match day is treated as known on that day.
- Absence from a captured squad without other evidence stays unknown. The 25% unresolved-weight limit was set before the prospective results and was not tuned.
- The FPL ingest does not record which identity rule matched. Reep can audit the map but is not part of the pipeline.
- Each propensity table is one pooled table. It is not different for division, club, season stage or manager change.
- A club promoted from League One has no lineup minutes before 2026/27, so it has no D until it has eight complete Championship matches.

Model interpretation:

- The starting-XI κ mixes a weak benched effect and a stronger absent-from-squad effect. The matchday-squad feature avoids this mixture, but it was chosen after the decomposition on the same seasons.
- The opening-season loss probably comes from a stale reference window after the summer, not from permanent departures. The data do not show demotions directly.
- The historical gain is concentrated in a few high-imbalance fixtures. A few prospective weeks cannot confirm or reject it.

## 9. Conclusions for Batch 2

### Historical mechanism

- The retained oracle result reproduces exactly on current `main`. Starting-XI discontinuity carries a temporary relative Quality signal, but the gain is concentrated, the opening five lose and 2025/26 is adverse.
- The roster decomposition shows where the signal is. A recent regular on the bench carries little of it. A recent regular who is absent from the matchday squad, departed or unresolved carries most of it. Permanent departures do not cause the opening-five loss.
- Matchday-squad discontinuity uses this directly. On the same chronological protocol it improves every proper score in all 12 competition-seasons, removes the opening-five loss and improves 2025/26. It is better than starting-XI discontinuity by −0.00174 score NLL [−0.00311, −0.00033].
- These are retrospective results on the seasons that suggested the hypotheses. The matchday-squad comparison was chosen after the decomposition, so it has more selection exposure than the retained feature.

### Measurement

- The same estimator runs at any cutoff. Its inputs degrade naturally with distance from kickoff: membership and recent selection are always present, and fixture injury lists and FPL status update when they are captured.
- In the development week, both features track their realized labels at 3 days, 24 hours and 90 minutes. The matchday-squad feature is measured more accurately at every scored horizon. At 90 minutes, its home-away correlation is 0.92 against 0.75 for the starting-XI feature, and it has no missed large imbalance.
- The estimate changes by 0.03 between 3 days and 24 hours and by 0.005 in the last day.
- No 6-day case is scored, and the samples are 11–23 fixtures. The horizon at which the measurement becomes reliable is not established. The first prospective rounds give 6-day and 3-day cases for the same fixtures.

### Forecast value

- No prospective fixture is scored.
- The development forecast differences are dominated by a few matches. Even the oracle with realized labels loses to the control in score NLL on the 11 three-day fixtures.
- No horizon-specific forecast value is established.

### Product implication

- The evidence supports the matchday-squad representation over the starting-XI representation: historically on every competition-season, and in measurement accuracy in the development week. The current mechanism does not need a detailed start-probability model. The start estimator stays as a prespecified baseline in the archive.
- The earliest useful horizon is not established. There is no evidence yet for a horizon gate, and no evidence that 24 hours is necessary.
- Batch 2 should decide from the prospective archive, using the frozen κ values: the measurement accuracy of D_squad at each horizon on the same fixtures, and the candidate minus control scores at each horizon.
- Batch 1 makes no production choice.

## 10. Frozen specification and prospective protocol

This section freezes the representation, the coefficient and the prospective evaluation. A later change must be recorded with its commit, and the archive must be made again.

### Representation and mapping

- D_squad = 1 − (recent minutes of players in the target matchday squad) / (all recent minutes). The recent minutes are the minutes, capped at 90, in the eight previous matches of the club before the target date. Each window match needs at least 700 recorded minutes.
- The temporary shift is κ(D_a − D_h) on the home log rate and −κ(D_a − D_h) on the away log rate, with κ = 0.43161578781583126. It does not change the persistent M7 state.
- κ was fitted once on all 8,073 realized oracle matches before 2026/27. It is not fitted again on 2026/27 outcomes.

### Estimator at a cutoff

- Only observations retrieved at or before the cutoff are used.
- Membership, availability and unresolved weight follow section 3. For the matchday squad, API-Football unavailable and FPL i, s, n or u give 0, doubtful and FPL d give 0.3, and FPL a gives 1.
- A member's probability is its availability × q(m, n) from the `squad_table` of `src/epl_forecast/research/start_propensity.json`.
- A departed player has probability 0. An unresolved player is left out, and a club with more than 25% unresolved recent weight gets no candidate.
- An official team sheet captured before the cutoff replaces the estimate with the observed matchday squad.
- The starting-XI quantities stay in the archive as a recorded baseline. They are not a candidate for production.

### Prospective evaluation

- Population: Premier League and Championship regular-season fixtures in 2026/27 that kick off from 17 September 2026 00:00 UTC.
- Snapshots: the same estimator at 6 days, 3 days, 24 hours and 90 minutes before kickoff, with the structural M7 control fitted from data retrieved before the London day of each cutoff.
- Measurement at each horizon: bias, mean absolute error and correlation of club D_squad, and of D_a − D_h, against the final matchday squad; sign agreement when the realized absolute difference is at least 0.10; estimates that change between consecutive horizons.
- Forecast value at each horizon: candidate minus control in score NLL, H/D/A log loss and Brier on fixtures with a candidate. Also report the oracle minus control, and the results on fixtures that have all four horizons.
- Uncertainty: resample whole match rounds, and show each round.
- Label: prospective evidence. It is the only evidence that is not exposed to the selection of D_squad from the historical seasons.

### Hindcast standard

- A retrospective evaluation of this model version uses the history-only hindcast of section 11: preceding matches and minutes, preceding matchday squads, dated departures and the rolling M7 state. It does not use final injury records whose publication time is unknown.
- Propensity tables and coefficients for a target season come from earlier seasons only.
- A replay with the current frozen specification is a diagnostic. It is not out-of-sample evidence.
