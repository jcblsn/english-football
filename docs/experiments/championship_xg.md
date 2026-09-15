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

## Coverage audit

`scripts/research/audit_xg_coverage.py` counts finished regular-season matches with API team xG for both teams. It reads R2 through an empty workspace. The result on 15 September 2026:

| Competition | Season | Matches with API xG | Evidence basis |
| --- | --- | ---: | --- |
| Premier League | 2022/23 | 193 of 380 | retrospective |
| Premier League | 2023/24–2025/26 | 380 of 380 in each season | retrospective |
| Premier League | 2026/27 | 30 of 40 | retrospective and captured |
| Championship | 2023/24 | 550 of 552 | retrospective |
| Championship | 2024/25–2025/26 | 552 of 552 in each season | retrospective |
| Championship | 2026/27 | 67 of 81 | retrospective and captured |
| League One | 2026/27 | 47 of 71 | captured |
| League Two | 2026/27 | 47 of 72 | captured |

There is no API xG before 2022/23 in any division, and no historical API xG in League One or League Two. The National League has none. The Championship has three fully covered seasons. The calibrated candidate needs 100 earlier API matches before it admits xG, so it starts in the autumn of 2023/24. The chronological Championship comparison therefore has two full seasons, 2024/25 and 2025/26, and one partial season, 2023/24. League One and League Two can only be evaluated prospectively.

## Semantic and synthetic checks

The tests on this branch pass:

- With s = 1, the likelihood, score and curvature are identical to the current M7 likelihood.
- A scaled observation equals the unit-scale likelihood at x / s, less a constant log s per observation. The constant is the same for each noise member, so the member weights do not change.
- The scaled joint density integrates to the Poisson goal marginal.
- Samples from the scaled model have E[X] = s × rate, and the calibrated estimator recovers s = 0.8 from simulated matches.
- A calibrated provider with fewer than the minimum earlier matches gives the goals-only filter exactly.
- The calibrated scale uses only observations available at the cutoff. A changed future xG value does not change the forecast.
- An incremental fit filters again from the start when the scale changes, and it agrees with a batch fit.
- Higher provider xG raises the attacking log rate of the team.

## Prospective archive

`scripts/research/archive_prospective_pair.py` makes a product control forecast and a candidate forecast from one cutoff, with the same code, seed and 10,000 paths. The candidate adds the calibrated API xG parameters to the product M7 specification. Both archives must pass the product checks. The pair stays in R2 also if the candidate is later rejected.

```sh
uv run python scripts/research/archive_prospective_pair.py --experiment championship-xg --competition eng-championship --candidate-parameters '{"xg_sources": [{"provider": "understat"}, {"provider": "api_football", "competitions": ["eng-championship"]}], "provider_scales": {"api_football": "calibrated"}}'
```

The first pair has the cutoff 2026-09-15T06:06:21Z and code commit `a7e5403`. It is at `research/evidence/championship-xg/prospective/eng-championship/20260915T060621Z` in `page324-data`. Both archives pass 1,582 of 1,582 product checks. The control filter uses no xG, because the Championship filter updates only from Championship matches. The candidate admits 1,721 API xG matches with a calibrated scale of 0.968. Across 471 remaining matches, the median largest H/D/A probability change is 0.030 and the maximum is 0.115. Make one pair before each Championship match round. Score the pairs on the prespecified slices after the results.
