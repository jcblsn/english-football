# Rolling personnel continuity and uncertainty

## Protocol

| Field | Value |
| --- | --- |
| Main base SHA | `f3660fe78367243290706acb406055ca422f559c` |
| Status | Stopped after the phase 1 oracle; no uncertainty signal |
| Historical evidence label | Retrospective development evidence |
| Authoritative data | Private R2 bucket `page324-data`, read through a new empty workspace under `runs/` |
| Control | Frozen M7 from the main base SHA |
| Claim that phase 1 can update | The information hypothesis: low personnel continuity makes M7 more uncertain than M7 thinks it is |

### Hypothesis and mechanism

A team state is filtered from matches that a specific group of players played. When the players available for a target fixture are not representative of that group, the persistent team state stays valid, but a temporary, zero-mean personnel-regime error is added. The model expresses this error as extra state covariance in the existing Quality/Tilt geometry. The mean Quality and Tilt do not change. The error is common to the fixtures in one personnel regime and it disappears when continuity returns.

For team i, target fixture f and cutoff c, the recent weight of player p is the minutes of p in the last N eligible matches of team i before c. With availability a in [0, 1]:

C = Σ w a / Σ w, and D = 1 − C.

### Structural comparator

M7 from the main base SHA, with the same fixtures, cutoffs and score law. In phase 2, the candidate is M7 plus g(D) extra state covariance and nothing else.

### Information cutoff

Phase 1 uses the realized target minutes. This is an oracle input that is not available before kickoff. Phase 1 results are not forecast results. The recent weights use only matches before the target date. The M7 forecasts use only results before the target date, with the product next-day availability convention.

Phase 3 uses availability evidence with a capture timestamp before the cutoff. The historical API injury records in R2 were all captured retrospectively on 8 September 2026, so historical replay of availability is not strict out-of-sample evidence. Phase 3 is prospective.

### Predeclared definitions

- Primary window: N = 8 eligible matches of the team in the same competition before the target date. No other window is searched.
- Oracle availability: a = min(target minutes, 90) / 90. A player who did not play has a = 0. A newcomer has no weight.
- Missing data: if the target lineup or the 8 recent lineups are incomplete, D is missing. It is not zero.
- Population: Premier League and Championship regular-season matches in 2017/18–2025/26. These are the seasons with lineup minutes for all matches and a previous season for the window. League One and League Two have lineup minutes only in 2026/27.

### Primary measurements for phase 1

All measurements use frozen M7 pre-match forecasts. For each team-match, D_own is the continuity loss of the scoring team and D_opp is the continuity loss of the conceding team.

- Squared standardized goal residual z² = (G − E[G])² / Var[G], where the moments come from the M7 predictive score distribution. Calibrated uncertainty gives E[z²] = 1.
- Score NLL of the realized score.
- Coverage of the central 80% predictive interval for team goals.
- Absolute H/D/A probability error.
- Log-rate error against an xG proxy: (log xG − E[log rate])² relative to Var[log rate]. Premier League uses Understat xG. Championship uses API xG in 2023/24–2025/26.

The central test is the slope of each measure on continuous D, with whole-season resampling. Deciles of D are descriptive only.

### Redirect or stop rule

If the oracle shows no increase of E[z²], score NLL or log-rate error with D, stop this uncertainty formulation. Do not continue to phase 2. If the relationship exists, fit the one-parameter monotone map extra covariance = κ D² in phase 2, on earlier seasons only. A phase 2 candidate that improves scores only by widening all fixtures is a failure.

## Phase 1 result

The oracle covers 16,776 Premier League and Championship team-matches in 2017/18–2025/26. 16,381 have a complete 8-match window and target lineup. 16,148 team-matches have D for both teams. Intervals resample 18 whole competition-seasons.

Slopes per unit of D, pooled, with minutes-based target availability:

| Measure | Own-team D | Opponent D | Seasons with positive own slope |
| --- | --- | --- | ---: |
| z² of team goals | −0.29 [−0.56, −0.02] | +0.45 [+0.19, +0.73] | 6 of 18 |
| Team-goal NLL | −0.39 [−0.53, −0.23] | +0.45 [+0.31, +0.58] | 2 of 18 |
| Outside the 80% interval | −0.038 [−0.095, +0.021] | +0.068 [−0.001, +0.144] | 7 of 18 |
| Signed goal residual | −0.68 [−0.92, −0.44] | +0.78 [+0.60, +0.97] | 3 of 18 |
| Log-xG error / log-rate variance | +11.8 [+2.9, +20.8] | −28.2 [−38.7, −18.3] | 9 of 12 |

At match level, score NLL does not change with D: home D −0.01 [−0.20, +0.19], away D +0.13 [−0.04, +0.30]. The central 80% coverage is 0.80–0.83 in each of the ten deciles of own-team D. Mean z² is 0.86–1.05 in each decile, with no trend.

### Diagnostics added after the primary result

These two diagnostics were not prespecified. They test the interpretation of the primary result. They do not search windows or thresholds.

- Mean-adjusted z²: the linear mean shift in D is removed before z² is calculated. The own-team slope stays negative, −0.31 [−0.56, −0.04]. The opponent slope is +0.52 [+0.29, +0.78].
- Starting XI target: realized minutes include red cards, injuries and substitutions in the target match. With availability from the starting XI only, the own-team z² slope is −0.29 [−0.55, −0.03] and the opponent slope is +0.09 [−0.15, +0.34]. Outside-80% slopes are −0.053 [−0.110, +0.008] and +0.033 [−0.026, +0.093]. Coverage is 0.79–0.83 in each decile. The signed residual still moves: own −0.41 [−0.58, −0.21], opponent +0.30 [+0.13, +0.47].

### Interpretation

Lower realized continuity does not make M7 more uncertain than M7 thinks it is. The own-team dispersion slope is negative in every version. The positive opponent dispersion slope in the minutes version goes away when in-match events are removed from the target. Coverage does not fall. The signal that is present is a mean effect: a team with low continuity scores fewer goals than M7 expects, and its opponent scores more.

## Decision

Stop the uncertainty formulation under the predeclared rule. Do not fit g(D) in phase 2. Do not build the deployable availability archive for this formulation.

This is strong evidence against the information hypothesis of the uncertainty channel, because the high-information oracle with actual target personnel shows no dispersion signal. It is not evidence that player absences have no mean effect. The mean effect is a separate hypothesis. It needs its own protocol, a cutoff-safe availability representation and an explanation of how it differs from the rejected known-minutes roster bridge on the research branch.

The personnel smoke test in `docs/smoke_tests.md` applies only if an uncertainty response is configured in a later product.

## Retained artifacts

- Primary oracle: `research/evidence/personnel-uncertainty/750d1b9/oracle-minutes` in `page324-data`. Code commit `750d1b9`.
- Added diagnostics: `research/evidence/personnel-uncertainty/750d1b9/oracle-sensitivity` in `page324-data`. The manifest records `750d1b9`, but the run used the diagnostic code that is committed as `1fd9f17`. It reuses the primary `team_matches.csv`, so M7 was not fitted again.

Reproduce with an empty workspace:

```sh
uv run python scripts/research/personnel_oracle.py --data runs/ws-oracle --output runs/personnel-oracle
uv run python scripts/research/personnel_oracle.py --data runs/ws-oracle-sensitivity --output runs/personnel-oracle-sensitivity --rows runs/personnel-oracle/team_matches.csv
```

### Limitations

- The oracle uses realized lineups, so it is not a forecast. The historical API injury records were captured retrospectively and were not used.
- Lineup minutes exist only for the Premier League and the Championship before 2026/27.
- One window, N = 8, was examined. A complete lineup needs at least 700 recorded minutes.
- The xG proxy is noisy, and Championship API xG covers only three seasons.
