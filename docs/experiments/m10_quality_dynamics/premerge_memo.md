# M10 pre-merge checks: memo

Status: retrospective development evidence, 17 September 2026. Branch: `research-m10-quality-dynamics`. Production branch: `m10-quality-dynamics`. The plan is in [premerge_plan.md](premerge_plan.md). It was recorded before any result of the candidates E1, S1 and S2. The tables are in [tables/premerge/](tables/premerge/).

## Summary

| Check | Result | Decision |
| --- | --- | --- |
| 1. Reference frame of the Quality level | The common direction has a bounded posterior SD of approximately 0.04. It gives 4–7% of the entrant-minus-incumbent Quality variance (3–6% in M7). Entrant forecasts referenced to the season mean are better in League Two only. | No change. Regression tests added. |
| 2. Entrant initialization | E1, which gives an entrant the entry-prior variance in total, is worse on entrant matches, on later matches and in the season panels. | Keep the current treatment. Document its meaning. |
| 3. Personnel adjustment on M10 | The frozen adjustment improves M10 by −0.00123 score NLL [−0.00202, −0.00048], 81% of its gain on M7. No slice reverses. | Keep the adjustment. The prospective control becomes M10. |
| 4. Close-season level transition | S1 is worse in score NLL. S2 is neutral and removes 25% of the early-EFL weakness, less than the one third that the plan required. | Keep M10. The search stops. |
| 5. Observability | Level–form covariance exposed, stale diagnostics corrected, fixed two-slot assumptions removed. | Production commit. |
| 6. Equivalence | See Section 6. | |

All match comparisons use the rolling daily forecasts of `m10_premerge_rolling.py` on the test seasons 2015/16–2025/26 (22,132 matches) with 28-day block intervals. The rolling M10 of this check gives the same match probabilities and score log probabilities as the M10 memo run in all four divisions (largest difference 0.0). The M10 minus M7 results of the memo are reproduced: −0.00107 log loss and −0.00076 score NLL.

## 1. Reference frame of the Quality level

The match likelihood sees only differences of Quality. The common Quality of all clubs is not observed. With a random-walk level, the question is whether the uncertainty of that common direction increases without a limit and whether it changes entrant forecasts, because an entry prior is referenced to zero.

`m10_frame.py` fits one member (chance probability 0.2) of M10 and of M7 at a preseason and a midseason cutoff of each season in each division. For the clubs that continue into the season, it measures the posterior mean and SD of their mean Quality, and the part of an incumbent's Quality variance that comes from this common direction (`tables/premerge/frame_summary.csv`). Means over 2012/13–2026/27, preseason:

| Division | Common SD M10 (M7) | Common SD at 2026/27 M10 (M7) | Frame variance M10 (M7) | Entrant Quality variance M10 (M7) | Offset from the season-mean reference M10 (M7) |
| --- | --- | --- | --- | --- | --- |
| Premier League | 0.047 (0.035) | 0.043 (0.033) | 0.0023 (0.0013) | 0.0202 (0.0148) | +0.056 (+0.036) |
| Championship | 0.043 (0.033) | 0.037 (0.029) | 0.0019 (0.0011) | 0.0254 (0.0200) | +0.005 (+0.004) |
| League One | 0.043 (0.034) | 0.038 (0.031) | 0.0019 (0.0012) | 0.0328 (0.0274) | +0.033 (+0.031) |
| League Two | 0.043 (0.034) | 0.037 (0.030) | 0.0019 (0.0012) | 0.0313 (0.0260) | −0.052 (−0.042) |

The findings:

- The common SD does not increase with time. It is 0.06–0.07 in 2012/13 and decreases to a stable 0.037–0.043. Each entrant has an independent prior with mean relative to the division, so each season of entrants fixes the frame again. The random walk makes the stable SD approximately 0.01 larger than in M7.
- The frame variance is the part of the entrant-minus-incumbent Quality variance that the common direction gives: approximately 0.002 in M10 and 0.001 in M7. With the entrant variance of 0.020–0.033 and the incumbent variance of 0.011–0.014, this is 4–7% of the Quality difference variance in M10 and 3–6% in M7. The Premier League has the largest share.
- The offset is the mean Quality of all clubs of the season, entrants included, which is the reference of the entry-prior labels. It is not zero, but it has the same sign in M7 and M10, and the M10 value is at most 0.02 larger. Thus it is mostly not a consequence of the random walk.
- A change of the frame changes entrant forecasts by construction. `tables/premerge/frame_entrants.csv` forecasts the first ten matches of each entrant against a continuing club from the preseason state, as the filter does and with the entrant referenced to the season mean, without the frame variance. The entrant win probability changes by 0.011 (Championship) to 0.032 (League Two). The referenced forecasts are better in League Two (−0.0109 log loss in matches 1–5 and −0.0067 in matches 6–10) and in League One matches 1–5. They are worse in the Championship matches 1–5 (+0.0034) and in the Premier League matches 6–10 (+0.0104). Pooled over the 2,320 entrant matches of 2015/16–2025/26, the reference changes the log loss by −0.0016 in M10 and by −0.0012 in M7. Almost all of that pooled gain is from League Two, and the part that M10 adds is 0.0004.

Decision: the frame issue is small in practice and bounded. The reference to the season mean does not improve most divisions, so the plan gives no fix. Two production tests protect the property: a change of the common Quality level (mean and variance) does not change the forecast between fitted clubs, and entrants keep the common SD bounded in a league with promotion and relegation (without entrants the same SD increases each season).

## 2. Entrant initialization

The entry-prior label is the division-relative strength of an entrant over its entry season. M10 gives the prior to the level and adds the stationary form variance 0.0054, so the total Quality variance of an entrant is larger than the prior. E1 kept the total: the level variance is the prior variance minus the form variance.

Match forecasts, E1 minus M10, ×1000 (`tables/premerge/rolling_comparisons.csv`):

| Slice | Matches | Log loss [95% interval] | Score NLL [95% interval] |
| --- | ---: | --- | --- |
| All | 22,132 | +0.17 [−0.01, +0.35] | +0.10 [−0.08, +0.28] |
| Entrant matches | 9,189 | +0.36 [−0.06, +0.78] | +0.21 [−0.23, +0.63] |
| Entrant matches, club match 1–5 | 1,067 | −0.06 [−0.76, +0.93] | −0.84 [−1.61, +0.36] |
| Entrant matches, club match 1–10 | 2,096 | −0.05 [−0.91, +0.93] | −0.61 [−1.55, +0.39] |
| Club match 21 and later | 11,924 | +0.29 [+0.09, +0.50] | +0.27 [+0.05, +0.48] |

Season panels, E1 minus M10 at preseason (`tables/premerge/panel_e1.csv`, `panel_e1_cohorts.csv`):

| Division | Rank RPS | Points CRPS [95% interval] | 90% width M10 → E1 | Promoted clubs: 90% coverage M10 → E1 |
| --- | --- | --- | --- | --- |
| Premier League | +0.0001 | +0.028 [+0.001, +0.056] | 33.5 → 33.1 | 78.8% → 72.7% |
| Championship | −0.0004 | −0.002 [−0.029, +0.028] | 42.3 → 41.2 | 93.9% → 93.9% |
| League One | +0.0001 | +0.020 [−0.014, +0.055] | 44.0 → 42.8 | 86.1% → 86.1% |
| League Two | +0.0002 | +0.020 [−0.005, +0.042] | 43.2 → 42.1 | 88.9% → 88.9% (from outside) |

Points CRPS is worse for E1 at 17 of 20 division-origins, and 7 intervals are above zero. Rank RPS is worse at 15 of 20, with one interval above zero. The narrower E1 prior helps the score NLL of the first entrant matches a little, but the later matches and the season distributions are worse. A probable cause is that a smaller level variance makes the entrant level learn more slowly, and the early results go more to the temporary form. The promoted-club intervals of the Premier League were already too narrow, and E1 makes them narrower.

Decision: the current treatment stays. It is not a double count in effect. The entry prior was calibrated on a season-average strength with the label noise removed, and it does not include the variation of Quality within a season. In M10, the stationary form variance adds that variation to the entrant. The semantics are: the entry prior describes the level of the entrant, and the form starts at zero with its stationary uncertainty.

## 3. Personnel adjustment on M10

`m10_personnel.py` applies the archived shifts of the history-only hindcast (`research/evidence/personnel-measurement/68cba95/pm-hindcast-report/chronological.csv`) to rolling M10 and M7 forecasts of the same 5,450 Premier League and Championship matches in 2020/21–2025/26. The M7 control of this run reproduces the archived M7 control score NLL to within 5e-15, so the two structural models are compared on exactly the archived population. No coefficient is fitted. Candidate minus control (`tables/premerge/personnel_summary.csv`, `personnel_intervals.csv`):

| Scope | Matches | M7: hindcast score NLL | M10: hindcast log loss | M10: hindcast Brier | M10: hindcast score NLL | M10: released κ score NLL |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| All | 5,450 | −0.00152 | −0.00109 | −0.00068 | −0.00123 | −0.00120 |
| Premier League | 2,280 | −0.00145 | −0.00150 | −0.00089 | −0.00112 | −0.00112 |
| Championship | 3,170 | −0.00158 | −0.00079 | −0.00053 | −0.00131 | −0.00125 |
| Opening five matches | 577 | −0.00116 | −0.00025 | +0.00003 | −0.00069 | −0.00023 |
| After the opening five | 4,873 | −0.00157 | −0.00118 | −0.00076 | −0.00129 | −0.00131 |
| 2025/26 | 907 | −0.00223 | −0.00059 | −0.00024 | −0.00192 | −0.00191 |
| Realized absolute D difference at least 0.20 | 403 | −0.01677 | −0.00961 | −0.00689 | −0.01559 | −0.01675 |

Intervals over 12 competition-season clusters for M10: hindcast log loss −0.00109 [−0.00177, −0.00051], Brier −0.00068 [−0.00110, −0.00030], score NLL −0.00123 [−0.00202, −0.00048] with 10 of 12 clusters below zero. The gain on M10 minus the gain on M7 is +0.00018 log loss [+0.00015, +0.00021] and +0.00029 score NLL [+0.00023, +0.00037], with the same sign in all 12 clusters. The oracle gain decreases by a similar proportion (−0.00365 → −0.00321).

Decision: the adjustment keeps 81% of its score NLL gain and has no reversed slice. The plan rule (a gain below zero of at least half the M7 gain) keeps it. The M10 form follows part of the same short changes of strength, which explains the small, consistent decrease. The prospective review must use M10 as its structural control for the fixtures forecast after the merge.

## 4. Close-season level transition

S1 adds a level innovation with SD 0.08 at the first match of a continuing club in a new season. S2 moves half of the annual level variance to that boundary (0.0566 in calendar time and 0.0566 at the boundary). Candidate minus M10, ×1000:

| Slice | M10 minus M7 log loss | S1 log loss | S1 score NLL [95% interval] | S2 log loss [95% interval] | S2 score NLL [95% interval] |
| --- | ---: | ---: | --- | --- | --- |
| All | −1.07 | −0.01 | +0.66 [+0.25, +1.07] | +0.00 [−0.15, +0.16] | +0.01 [−0.17, +0.21] |
| Premier League | −2.68 | +0.26 | +0.53 [−0.42, +1.44] | +0.10 [−0.21, +0.40] | +0.03 [−0.35, +0.41] |
| EFL | −0.69 | −0.07 | +0.69 [+0.24, +1.17] | −0.02 [−0.17, +0.15] | +0.01 [−0.17, +0.23] |
| EFL club match 1–5 | +1.54 | +0.43 | +1.77 [+0.90, +2.55] | −0.38 [−0.61, −0.09] | −0.23 [−0.56, +0.13] |
| EFL club match 6–10 | −0.54 | −0.49 | +0.67 [−0.87, +2.19] | +0.29 [−0.25, +0.80] | +0.59 [−0.17, +1.25] |

The plan rules:

1. Pooled log loss and score NLL lower than M10: S1 fails (score NLL +0.00066), S2 fails (+0.00000 and +0.00001).
2. Premier League log loss not worse by more than 0.0005: both pass.
3. EFL matches 1–5 better by one third of the M10 gap (0.00051): S1 fails (worse), S2 fails (0.00038, 25% of the gap).

Neither candidate passes, so the season panels were not run. S2 moves a small part of the early EFL weakness from matches 1–5 to matches 6–10 and gives no net gain. A larger boundary innovation (S1) makes the score distributions too wide. The hypothesis that a close-season change of the level explains the early EFL weakness has no support in this form. M10 stays, and no further σ_c is tested.

## 5. Observability and stale semantics

Production commits on `m10-quality-dynamics`:

- The state summary and `analysis.model_team_states` have `quality_level_form_covariance`. The Quality variance is the level variance plus the form variance plus twice this covariance, and a test checks the identity. It is negative after results, because the observations inform the sum of level and form more than each part.
- The fit diagnostics no longer describe M4 promotion priors or M5 dynamics. They state the Quality dynamics of each specification and the entry rule.
- The `team_dimensions` review: the base attack and defense properties and the entrant draws of the base sampler used two slots per club, the transition silently accepted a state size that is not a whole number of club blocks, and the centered coordinates assumed without a check that Tilt is the second club slot. Each of these now uses the club block size or fails with a clear error.

## 6. Equivalence of production and research

PENDING

## Reproduce

```sh
uv run --with pandas --with pyarrow python scripts/research/m10_frame.py --output runs/m10-frame
uv run --with pandas --with pyarrow python scripts/research/m10_frame.py --output runs/m10-frame --tables docs/experiments/m10_quality_dynamics/tables/premerge
uv run --with pandas --with pyarrow python scripts/research/m10_premerge_rolling.py --output runs/m10-premerge --competitions <division> --candidates <M7|M10|E1|S1|S2>
uv run --with pandas --with pyarrow python scripts/research/m10_premerge_analysis.py --rolling runs/m10-premerge --tables docs/experiments/m10_quality_dynamics/tables/premerge
uv run python scripts/research/m10_premerge_panel.py --candidate E1 -- --models M10 --competition <division> --seasons <seasons> --output runs/m10-premerge-panels/E1-<division>
uv run --with pandas python scripts/research/m10_premerge_panel_report.py --control runs/m10-panels --panels runs/m10-premerge-panels --candidate E1 --tables docs/experiments/m10_quality_dynamics/tables/premerge
uv run --with pandas --with pyarrow python scripts/research/m10_personnel.py --evidence <chronological.csv> --rolling runs/m10-premerge --tables docs/experiments/m10_quality_dynamics/tables/premerge
```

Run the scripts from a checkout of `m10-quality-dynamics` so that `epl_forecast` is the production M10. The control panels `runs/m10-panels/c2-<division>` are those of the M10 memo.
