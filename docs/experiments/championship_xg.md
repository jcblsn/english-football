# Championship API xG as an observation of team scoring strength

## Protocol

| Field | Value |
| --- | --- |
| Main base SHA | `f3660fe78367243290706acb406055ca422f559c` |
| Status | Coverage audit and observation model |
| Historical evidence label | Retrospective development evidence |
| Authoritative data | Private R2 bucket `page324-data`, read through a new empty workspace under `runs/` |
| Control | Championship M7 from the main base SHA, goals only |
| Candidate | The same M7 dynamics, entry priors, filters, score law and simulator, with calibrated API xG observations |

### Hypothesis and mechanism

API-Football `team_statistics.expected_goals` is a noisy measurement of the same latent scoring rate that the M7 opportunity model already uses for Understat xG. When the filter admits it as a likelihood, the Championship team state becomes more accurate earlier. The earlier residual study on the research branch asked whether a residualized sensor predicts later goals. It did not ask this question.

### Observation model

The current M7 channel is the special case s = 1 of a provider-scaled opportunity model:

- N | λ, p ~ Poisson(λ / p)
- G | N, p ~ Binomial(N, p)
- X | N, p, s ~ Gamma(N, s p), so E[X | λ] = s λ.

The existing prior over the opportunity-noise parameter p is kept. The provider scale s is estimated from earlier observations only, as the ratio of total provider xG to total goals in the matches available before the cutoff. It is not chosen by H/D/A scores. API xG and Understat xG are not combined as independent sensors.

### Semantic and synthetic checks

- s = 1 gives the current M7 likelihood exactly.
- A match without provider xG gives the goals-only likelihood exactly. Missing xG is never zero.
- Disabling the channel gives the goals-only control exactly.
- Simulated data with a known s recovers s and moves the state in the direction of the xG evidence.
- xG observed after a cutoff cannot change the forecast at that cutoff.

### Premier League positive control

On exactly matched Premier League matches, compare goals-only M7, Understat-xG M7, raw API-xG M7 (s = 1) and calibrated API-xG M7. If Understat xG improves on goals only but calibrated API xG does not recover a similar direction, diagnose provider semantics, scaling, likelihood, chronology and numerical inference before making a Championship claim.

### Information cutoff

Provider xG is assumed available on the day after the match, as for Understat in M7. The historical API rows were captured retrospectively, so this is an assumption and not a proven publication time.

### Primary measurements

Match forecasts: H/D/A log loss, Brier, score NLL, calibration, per-season results, opening five fixtures, promoted and relegated clubs, matches after a large goal/xG disagreement, and posterior Quality/Tilt uncertainty. Also check that xG moves the states in sensible directions and by sensible magnitudes.

Season forecasts: rank RPS, points CRPS, 50/80/90% interval coverage and width, and title, automatic promotion, playoff and relegation Brier scores at preseason, MW6, MW12, MW19 and MW30, with identical origins, schedules, seeds, path counts and rules.

### Uncertainty

Few Championship seasons have full API xG coverage. Show each season, pooled matched differences as description and the mechanism diagnostics. Do not present a two-season interval as strong inference. The 2026/27 prospective archive of goals-only and xG candidates is the confirmation sample.

### Redirect or stop rule

Stop the Championship comparison if the semantic checks fail or if the Premier League positive control cannot be explained. A failed raw API candidate does not show that xG is useless. A failed calibrated observation model is evidence against that representation. Park the channel only if credible representations fail both the positive control and the Championship high-information test.
