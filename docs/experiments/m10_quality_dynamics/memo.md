# M10 Quality dynamics: memo

Status: retrospective development evidence, 17 September 2026. Branch: `research-m10-quality-dynamics`. Main base: `c7d94c7`. The plan, recorded before the candidate results, is in [plan.md](plan.md). The tables are in [tables/](tables/). The production candidate is on the branch `m10-quality-dynamics`. It is not merged.

## Terms

- Quality level (L): the persistent strength of a club.
- Form (F): a deviation of Quality from L that returns to L.
- AR(1): a process that returns to zero with an annual retention ρ and an annual innovation SD σ.
- Random walk: an AR(1) process with ρ = 1. It does not return to a mean.
- Outcome stretch: the best power on the home/away odds of a forecast, with the draw probability fixed. A value above 1 shows that the forecast makes the differences between clubs too small. It does not use the market.
- Forward-chaining selection (FC): for each test season, the candidate with the lowest pooled score NLL in all four divisions on the seasons from 2012/13 to the previous season.
- BMA: an average over candidates with weights from the chronological evidence of each filter.
- Test seasons: 2015/16–2025/26, which is 22,132 matches in four divisions.

## Recommendation

M10 is Quality = L + F. L is a random walk with σ_L = 0.08. F is an AR(1) process with ρ_F = 0.3 and σ_F = 0.07. Everything else is M7. The forecasts are better than M7 in the pooled test, in the Premier League and in League One. They are neutral in the Championship and mixed in League Two. SEASON-PANEL-VERDICT

## 1. The cause

M7 Quality is one AR(1) process with ρ = 0.85 and σ = 0.09. Thus the Quality of every club returns to the league mean with a half-life of 4.3 years. The results below show three parts of the weakness.

1. The return to the league mean is too strong for the persistent level. In the Premier League, a random walk with the same σ decreases the log loss by 0.0021 [−0.0029, −0.0012]. Almost all of this gain is in matches with a club in the top or bottom quintile of opening Quality. The gain is −0.0004 in matches between middle clubs (`tables/comparisons.csv`, first grid).
2. The innovation scale is too small. At ρ = 0.85, σ = 0.12 is better than σ = 0.09 in all four divisions. At σ = 0.06, every ρ is worse. A larger σ makes the stationary distribution wider and the filter faster. The martingale test gives the same result: in M7, a change of Quality in the last five matches predicts a later change in the same direction in every division (slope +0.004 to +0.048, `tables/martingale.csv`). Thus M7 learns new information too slowly.
3. One process cannot be persistent and fast together. A random walk that is fast enough to follow a change of form keeps the change for ever. The C2 structure removes this conflict. In the martingale test, the C2 slopes are the nearest to zero at five matches (−0.0003 to +0.020).

The divisions do not agree on the persistence of the level. The random walk is much better in the Premier League, a little better in the Championship and League One, and a little worse in League Two. In League Two, M7 has no outcome stretch (1.08), and within a season a club with a high Quality falls more than every candidate expects (level slope −0.01 to −0.04). League Two has the most change of squads and the most regression of strong clubs.

The earlier hypotheses of the disagreement memo agree with this cause. The return to the mean compresses the persistent level of clubs that are strong or weak for many seasons. But the more expressive structure is necessary: the random walk alone does not improve the EFL.

## 2. The structural alternative

The plan fixed three structures before the results: a grid of AR(1) dynamics (C1), a chronological selection or average over that grid, and a level plus form (C2). The table gives the pooled test and each division. Lower is better. The control is M7.

| Candidate | All log loss | All score NLL | PL score NLL | Championship | League One | League Two |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| M7 (ρ 0.85, σ 0.09) | 1.03503 | 2.87716 | 2.92697 | 2.83223 | 2.88587 | 2.87935 |
| AR(1) ρ 0.85, σ 0.12 | 1.03428 | 2.87677 | 2.92609 | 2.83218 | 2.88521 | 2.87923 |
| Random walk, σ 0.09 | 1.03454 | 2.87681 | 2.92500 | 2.83203 | 2.88578 | 2.87974 |
| C1-FC | 1.03446 | 2.87696 | 2.92585 | 2.83227 | 2.88565 | 2.87958 |
| C1-BMA | 1.03440 | 2.87679 | 2.92566 | 2.83218 | 2.88525 | 2.87954 |
| C2-FC | 1.03396 | 2.87640 | 2.92430 | 2.83184 | 2.88513 | 2.87953 |
| C2-BMA | 1.03404 | 2.87647 | 2.92462 | 2.83187 | 2.88508 | 2.87960 |

C1-FC is not stable. It selects ρ = 0.85, σ = 0.12 in most seasons, but it selects the random walk in 2019/20 and 2020/21. It is worse than the best fixed C1 point. The C1 average is no better than the best fixed point.

C2-FC is stable. The first C2 grid (σ_L ∈ {0.04, 0.06}, σ_F ∈ {0.10, 0.15}) selected σ_L = 0.06, σ_F = 0.10 in every season from 2015/16. That point was at the edge of the grid. The plan amendment added three outward points before their results. The extended selection is σ_L = 0.08, σ_F = 0.07 in every season from 2015/16. The surface is flat near these points: the four best C2 points differ by less than 0.0002 in pooled score NLL. The selected point is again at an edge, but a further search could not give a material gain. A form SD of 0.15 is clearly worse. ρ_F = 0.3 was fixed before the results and was not searched.

C2-FC is better than the best alternatives on the same matches (`tables/form_comparisons.csv`):

| C2-FC minus | Log loss [95% interval] | Score NLL [95% interval] |
| --- | --- | --- |
| C1-FC | −0.00049 [−0.00073, −0.00026] | −0.00057 [−0.00085, −0.00029] |
| Random walk, σ 0.09 | −0.00058 [−0.00085, −0.00030] | −0.00042 [−0.00073, −0.00012] |

Thus the form component adds evidence beyond a persistent level. Most of that addition is in the EFL.

## 3. Improvement of match and score forecasts

C2-FC minus M7 on the test seasons. The intervals resample 28-day blocks in each season (`tables/comparisons.csv`).

| Slice | Matches | Log loss [95% interval] | Score NLL [95% interval] | Brier |
| --- | ---: | --- | --- | ---: |
| All | 22,132 | −0.00107 [−0.00151, −0.00062] | −0.00076 [−0.00128, −0.00022] | −0.00070 |
| Premier League | 4,180 | −0.00268 [−0.00363, −0.00170] | −0.00267 [−0.00412, −0.00121] | −0.00172 |
| Championship | 6,072 | −0.00064 [−0.00136, +0.00008] | −0.00039 [−0.00124, +0.00048] | −0.00046 |
| League One | 5,920 | −0.00125 [−0.00202, −0.00051] | −0.00074 [−0.00175, +0.00027] | −0.00083 |
| League Two | 5,960 | −0.00019 [−0.00095, +0.00055] | +0.00018 [−0.00063, +0.00095] | −0.00011 |
| EFL | 17,952 | −0.00069 [−0.00116, −0.00024] | −0.00032 [−0.00083, +0.00023] | −0.00046 |
| Entrant matches | 9,189 | −0.00088 [−0.00150, −0.00027] | −0.00043 [−0.00120, +0.00030] | −0.00055 |
| Continuing matches | 12,943 | −0.00120 [−0.00173, −0.00065] | −0.00099 [−0.00165, −0.00033] | −0.00081 |
| A club in its first 10 matches | 5,109 | −0.00053 [−0.00146, +0.00035] | −0.00009 [−0.00137, +0.00108] | −0.00037 |
| Later matches | 17,023 | −0.00123 [−0.00176, −0.00071] | −0.00096 [−0.00156, −0.00037] | −0.00080 |
| A top-quintile club | 8,379 | −0.00104 [−0.00179, −0.00031] | −0.00038 [−0.00126, +0.00056] | −0.00061 |
| A bottom-quintile club | 8,379 | −0.00127 [−0.00200, −0.00049] | −0.00089 [−0.00176, +0.00003] | −0.00079 |
| Two middle clubs | 7,359 | −0.00111 [−0.00177, −0.00047] | −0.00106 [−0.00189, −0.00024] | −0.00079 |

For scale, the documented M7 gain over M2 in the Premier League scoreboard is 0.0018 log loss. The M10 gain in the Premier League is larger than that.

Calibration (`tables/summary.csv`):

| Division | Outcome stretch M7 → M10 | Classwise ECE M7 → M10 |
| --- | --- | --- |
| Premier League | 1.24 → 1.15 | 0.0225 → 0.0179 |
| Championship | 1.15 → 1.08 | 0.0146 → 0.0128 |
| League One | 1.27 → 1.17 | 0.0149 → 0.0120 |
| League Two | 1.08 → 1.00 | 0.0115 → 0.0126 |

M10 removes approximately 40% of the excess stretch in the Premier League and League One. The stretch that remains is still above 1 in those divisions. League Two has no excess stretch after the change.

The spread of club Quality at the end of a season increases by approximately 8–13% (for example 0.192 → 0.208 in the Premier League, `tables/division_mean_quality.csv`). The mean Quality of a division stays within 0.05 of zero. Thus the division scale stays consistent with the entry priors without the return to the mean.

## 4. Seasons and divisions

Season effects, C2-FC minus M7, ×1000 (`tables/season_differences.csv`):

| Season | PL log loss | Ch. log loss | L1 log loss | L2 log loss | Pooled log loss | Pooled score NLL |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2015/16 | −0.9 | −0.5 | −0.3 | −2.7 | −1.1 | −0.8 |
| 2016/17 | −5.5 | −1.0 | −1.5 | +0.4 | −1.6 | −1.3 |
| 2017/18 | −2.5 | −2.3 | 0.0 | +0.1 | −1.1 | −0.6 |
| 2018/19 | −6.1 | −1.5 | −2.3 | +1.1 | −1.9 | −1.0 |
| 2019/20 | −0.5 | +0.6 | −0.9 | −0.3 | −0.2 | −0.5 |
| 2020/21 | −1.4 | +0.5 | +2.2 | +2.8 | +1.2 | +1.5 |
| 2021/22 | −4.1 | −1.0 | −3.9 | −1.7 | −2.5 | −3.5 |
| 2022/23 | −1.6 | +0.8 | −2.4 | 0.0 | −0.7 | −0.5 |
| 2023/24 | −4.2 | −1.0 | −1.9 | +0.7 | −1.4 | −1.1 |
| 2024/25 | −1.9 | −0.3 | −2.1 | +0.8 | −0.8 | +0.2 |
| 2025/26 | −0.9 | −1.3 | −0.5 | −3.1 | −1.5 | −0.8 |

- Pooled: the log loss is lower in 10 of 11 seasons, and the score NLL in 9 of 11. The failure is 2020/21, when the stadiums were empty.
- Premier League: log loss lower in 11 of 11 seasons, score NLL in 8 of 11.
- Championship: 8 and 7 of 11. League One: 10 and 6 of 11. League Two: 5 and 3 of 11.

League Two is a failure on score NLL. The League Two change is small in both directions and has no consistent sign.

The early matches of a season are a second failure (`tables/comparisons.csv` and the phase breakdown below). In each EFL division, M10 is worse than M7 in the first five matches of a club. It is better later. In the Premier League, it is better in every phase.

| Club match in season | PL log loss | Ch. log loss | L1 log loss | L2 log loss |
| --- | ---: | ---: | ---: | ---: |
| 1–5 | −4.4 | +2.4 | +0.2 | +2.4 |
| 6–10 | −4.1 | +0.1 | −0.1 | −1.7 |
| 11–20 | −1.8 | −1.5 | −0.4 | +0.6 |
| 21+ | −2.3 | −1.0 | −2.1 | −0.7 |

The same pattern is in the partial 2026/27 season, which is all early matches (266 matches): Premier League −3.8, Championship −0.7, League One +6.4 and League Two +5.7 log loss ×1000. These early 2026/27 matches were not part of any selection.

The interpretation is that a close season changes EFL clubs more than a calendar-time random walk permits. The squads of EFL clubs change much more in the summer. M7 returned the Quality to the mean over the close season, and that return was partly correct for EFL clubs. This interpretation comes after the results. It is a hypothesis for the next experiment, not a part of M10.

## 5. Season-level calibration and uncertainty

SEASON-PANEL-SECTION

## 6. Market residuals

These diagnostics come after the outcome evaluation. They were not a selection criterion. Premier League, 3,800 matches in 2016/17–2025/26, average pre-closing market (BetBrain average before 2019/20) (`tables/market_summary.csv`, `tables/market_clubs.csv`).

| Forecast | Market slope | Mean squared residual | Scale share | Club share |
| --- | ---: | ---: | ---: | ---: |
| M7 | 1.22 | 0.150 | 29% | 56% |
| AR(1) ρ 0.85, σ 0.12 | 1.17 | 0.145 | 19% | 52% |
| Random walk, σ 0.09 | 1.12 | 0.118 | 12% | 42% |
| M10 | 1.12 | 0.113 | 14% | 43% |

Club effects in 2023/24–2025/26, market minus model, with no scale term:

| Club | M7 | M10 | Change |
| --- | ---: | ---: | --- |
| Manchester City | +0.45 | +0.32 | Decreases by 30% |
| Liverpool | +0.27 | +0.16 | Decreases by 40% |
| Chelsea | +0.24 | +0.17 | Decreases by 30% |
| Arsenal | +0.31 | +0.23 | Decreases by 25% |
| Manchester United | +0.24 | +0.20 | Decreases a little |
| Tottenham | +0.15 | +0.13 | Stays |
| Aston Villa | +0.16 | +0.16 | Stays |
| Brentford | −0.27 | −0.27 | Stays |
| Crystal Palace | −0.26 | −0.25 | Stays |
| Wolves | −0.13 | −0.10 | Stays |
| Sheffield United | −0.24 | −0.18 | Decreases a little |
| Luton | −0.24 | −0.20 | Stays |
| Leicester | −0.18 | −0.13 | Decreases a little |

The residuals that disappear in part are the persistent levels of the historically strong clubs: City, Liverpool, Chelsea and Arsenal. The residuals that remain are:

- The mid-table clubs of the disagreement memo, Brentford, Crystal Palace and Wolves. These clubs have long goal-minus-xG gaps, or information outside the model.
- Tottenham and Aston Villa, which score more goals than their xG.
- Most of the promoted-club residual. For these clubs, the market has a lower view for all of a season. The entry priors do not change in M10.

The market slope is still 1.12 and club effects still explain 43% of the squared residual. Thus M10 is not a copy of the market, and the market still has information that M10 does not use.

## 7. Evidence against M10

- All evidence is retrospective. M7 was developed on the same seasons, and the disagreement memo that gave the hypotheses used the Premier League seasons 2016/17–2025/26. The EFL divisions and the seasons before 2016/17 were not used to make the hypotheses. The EFL gain is smaller than the Premier League gain.
- League Two does not improve, and its score NLL is worse in 8 of 11 seasons.
- In the EFL, M10 is worse in the first five matches of a club, and the partial 2026/27 season in League One and League Two is worse. A preseason forecast depends most on these matches.
- The selected point is at the edge of the extended grid. The surface is flat, so the choice between near points has no support from the data.
- ρ_F = 0.3 was not tested.
- The within-season level test in the Premier League shows that clubs with a high Quality fall a little more than M10 expects (slope −0.029 at ten matches). M7 does not have this problem there. Some return of the level may be real.
- A random walk level has no stationary distribution. The uncertainty of a club that leaves the data increases without a limit. Such a club uses its entry prior when it comes back, so forecasts do not use that uncertainty. But the state summaries of a club with a long gap are wider than before.
- The personnel coefficient κ and its prospective review were fitted against M7 structural forecasts. The market pool weight was fitted on M7 predictions. SEASON-PANEL-AGAINST

## 8. Merge decision

MERGE-DECISION

## Reproduce

```sh
uv run --with pandas --with pyarrow python scripts/research/m10_rolling.py --output runs/m10-grid --competitions <division> --candidates <candidate>
uv run --with pandas --with pyarrow python scripts/research/m10_analysis.py
uv run --with pandas --with pyarrow python scripts/research/m10_market.py --candidates r0.85-s0.09 r1.00-s0.09 level-s0.06-form-s0.10 r0.85-s0.12
uv run --with pandas --with pyarrow python scripts/research/m10_panel.py --candidate level-s0.08-form-s0.07 -- --models M10 --competition <division> --seasons <seasons> --output runs/m10-panels/c2-<division>
uv run python scripts/evaluate_seasons.py --models M7 --competition <division> --seasons <seasons> --output runs/m10-panels/control-<division>
uv run --with pandas python scripts/research/m10_panel_report.py
```

The control panels ran at `c7d94c7`. The rolling forecasts of the first grid ran at `91973ff`, and the extension and the candidate panels at `2a84dca`. Each job read the R2 catalog in its own process. The production M10 of the branch `m10-quality-dynamics` gives the same Premier League match probabilities as the rolling run of the selected candidate, to within 1e-15.
