# Rolling personnel continuity and uncertainty

## Protocol

| Field | Value |
| --- | --- |
| Main base SHA | `f3660fe78367243290706acb406055ca422f559c` |
| Status | Phase 1 oracle ceiling |
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
