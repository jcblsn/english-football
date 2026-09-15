# Championship API xG as an observation of team scoring strength

## Protocol

| Field | Value |
| --- | --- |
| Main base SHA | `f3660fe78367243290706acb406055ca422f559c` |
| Status | Historical evidence favorable; prospective confirmation in progress; not on main |
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

## Season panel

The panel forecasts the Championship seasons 2023/24, 2024/25 and 2025/26 from five origins with product M7 and with `M7-API-XG`. Both models use the same code commit `4c38c5e`, origins, schedules, seed 20260908, 10,000 paths and rules. `M7-API-XG` is product M7 with calibrated API Championship xG. 72 club-seasons are scored at each origin.

Candidate minus control. Negative is better.

| Season | Origin | Rank RPS | Points CRPS |
| --- | --- | ---: | ---: |
| 2023/24 | preseason | 0.00000 | 0.000 |
| 2023/24 | MW6 | 0.00000 | 0.000 |
| 2023/24 | MW12 | +0.00041 | −0.342 |
| 2023/24 | MW19 | +0.00024 | −0.286 |
| 2023/24 | MW30 | −0.00171 | −0.314 |
| 2024/25 | preseason | −0.01225 | −0.570 |
| 2024/25 | MW6 | −0.00850 | −0.041 |
| 2024/25 | MW12 | −0.00989 | −0.198 |
| 2024/25 | MW19 | −0.00763 | −0.168 |
| 2024/25 | MW30 | −0.00280 | +0.054 |
| 2025/26 | preseason | −0.00423 | −0.134 |
| 2025/26 | MW6 | −0.01558 | −0.621 |
| 2025/26 | MW12 | −0.01514 | −0.577 |
| 2025/26 | MW19 | +0.00437 | +0.200 |
| 2025/26 | MW30 | −0.00423 | −0.198 |

The 2023/24 preseason and MW6 forecasts are identical, because fewer than 100 earlier API xG matches were available. This is the expected chronology.

Pooled over the three seasons, the candidate has lower rank RPS at every origin: −0.0055 at preseason, −0.0080 at MW6, −0.0082 at MW12, −0.0010 at MW19 and −0.0029 at MW30. Points CRPS is lower at every origin, from −0.08 at MW19 to −0.37 at MW12. The report also gives whole-season resampled intervals. With three season clusters, and one season with no change at two origins, these intervals are not useful inference and this record does not use them.

The candidate intervals are narrower. The 90% points width decreases by 0.6 to 1.5 points. Points coverage changes by origin: 80% coverage decreases at preseason (0.819 to 0.806), MW6 (0.806 to 0.778), MW12 (0.792 to 0.750) and MW30 (0.819 to 0.778), and 90% coverage increases at MW12 (0.889 to 0.944), MW19 (0.917 to 0.931) and MW30 (0.847 to 0.875). Relegation Brier is lower at every origin. Promotion Brier is lower at preseason, MW6, MW12 and MW19 and higher at MW30 (+0.0027).

The panel is at `research/evidence/championship-xg/4c38c5e/season-panel` in `page324-data`. Reproduce with an empty workspace:

```sh
uv run python scripts/evaluate_seasons.py --data runs/ws-xg-panel --competition eng-championship --models M7 M7-API-XG --seasons 2023 2024 2025 --output runs/xg-season-panel
uv run python scripts/report_seasons.py --evaluation runs/xg-season-panel --output runs/xg-season-panel/report --baseline M7
```

## Match result

All arms use code commit `77b685e`, daily refits with results and xG available on the next day, and identical matches. Negative differences favor the candidate. Log-loss intervals use paired 28-day blocks within seasons. They are descriptive, because the blocks come from three seasons.

### Premier League positive control

1,140 matched matches in 2023/24–2025/26. Each arm minus goals-only M7:

| Arm | Log loss | 95% block interval | Brier | Score NLL | Classwise ECE |
| --- | ---: | --- | ---: | ---: | ---: |
| Goals only | 0.98296 | — | 0.58536 | 2.97567 | 0.02729 |
| Understat xG | −0.00439 | [−0.01060, +0.00198] | −0.00369 | −0.00289 | 0.03442 |
| Raw API xG, s = 1 | −0.00530 | [−0.01197, +0.00146] | −0.00432 | −0.01288 | 0.03150 |
| Calibrated API xG | −0.00516 | [−0.01174, +0.00153] | −0.00424 | −0.01168 | 0.03253 |

Per season, calibrated API xG changes log loss by +0.00355, −0.01729 and −0.00172. Understat changes it by +0.00499, −0.01432 and −0.00383. API xG recovers the same direction and a similar size as Understat, so the observation architecture passes the positive control. The calibrated Premier League scale is 1.06 at the start of 2023/24 and 0.99 after 2024. Both xG channels reduce the mean Quality SD from about 0.092 to about 0.076.

### Championship

1,656 matched matches in 2023/24–2025/26. Each arm minus product M7:

| Arm | Log loss | 95% block interval | Brier | Score NLL | Classwise ECE |
| --- | ---: | --- | ---: | ---: | ---: |
| Product M7 | 1.04349 | — | 0.62788 | 2.83783 | 0.01408 |
| Raw API xG, s = 1 | −0.00554 | [−0.00900, −0.00174] | −0.00382 | −0.01081 | 0.01446 |
| Calibrated API xG | −0.00542 | [−0.00919, −0.00118] | −0.00381 | −0.00828 | 0.01648 |

Calibrated API xG by season and slice:

| Scope | Matches | Log loss | Brier | Score NLL |
| --- | ---: | ---: | ---: | ---: |
| 2023/24 | 552 | −0.00937 | −0.00691 | −0.01156 |
| 2024/25 | 552 | −0.00263 | −0.00174 | −0.00672 |
| 2025/26 | 552 | −0.00427 | −0.00279 | −0.00655 |
| Opening five fixtures | 180 | +0.00347 | +0.00262 | +0.00503 |
| Entrant clubs | 738 | −0.00694 | −0.00498 | −0.01400 |
| After a goal/xG gap of at least 1.5 | 359 | −0.01289 | −0.00944 | −0.01844 |

Every season improves on all three scores. The largest gain follows a large disagreement between goals and xG, which is where the mechanism says xG adds information. The opening five fixtures are slightly worse. The calibrated scale starts at 0.91 in December 2023 and increases to 0.96 by 2026. The mean Quality SD falls from about 0.092 to about 0.075. The median largest H/D/A probability change is small, and the mean absolute change in the two expected goals is 0.17.

## Decision

The mechanism checks pass. The Premier League positive control is interpretable. On chronological history, calibrated API xG improves Championship match log loss, Brier and score NLL in each of the three covered seasons, and it lowers pooled rank RPS and points CRPS at every season-panel origin.

This is retrospective development evidence from three seasons. The API rows were captured after the seasons, so next-day availability is an assumption. Classwise ECE increases, the opening five fixtures are slightly worse, the 80% points coverage decreases at four of five origins and the MW30 promotion Brier is worse. Raw and calibrated API xG give similar results, so this evidence cannot separate the two representations. Calibration is kept because it is the coherent measurement model.

Do not move the channel to `main` yet. Continue the prospective archive through 2026/27, with one pair before each Championship round, and score the prespecified slices. Move a focused production change only if the prospective record agrees with the historical direction without a material calibration loss. Evaluate League One and League Two API xG only prospectively, when enough captured rows exist.

The match run is at `research/evidence/championship-xg/77b685e/match` and the coverage audit is at `research/evidence/championship-xg/77b685e/coverage-audit` in `page324-data`. Reproduce each arm with an empty workspace, then report:

```sh
uv run python scripts/research/evaluate_xg_observation.py predict --competition eng-championship --arm api-calibrated --data runs/ws-xg-championship-api-calibrated --output runs/xg-match/eng-championship
uv run python scripts/research/evaluate_xg_observation.py report --competition eng-championship --data runs/ws-xg-report --output runs/xg-match/eng-championship
```


### Schedule

A per-user launchd agent on the operator Mac runs the pair runner once each 24 hours from this worktree, and once when it is loaded. The data come from R2 and the forecasts use the product freshness check, so a pair is made before the next match round. Logs are in `runs/prospective/` of the worktree. The job was installed on 15 September 2026 with `epl_forecast.pipeline.install_launch_agent`. Remove it with `launchctl bootout gui/$(id -u)/org.epl-forecast.prospective-championship-xg` and delete `~/Library/LaunchAgents/org.epl-forecast.prospective-championship-xg.plist`.
