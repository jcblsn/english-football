# Root causes of M7–market disagreement

Status: retrospective development evidence, 17 September 2026. Branch `research-market-disagreement`, main base `c7d94c7`. The plan is in [plan.md](plan.md). The tables are in [tables/](tables/).

## Summary

1. M7 is too narrow on team strength differences. The market directional log-odds is about 1.2 times the M7 value in each of ten seasons. The outcomes agree without the market: the log-loss-optimal stretch of M7 directional log-odds is 1.27 in 2016–2026, against 1.04 for the market and 1.09 for M2.
2. In the market disagreement, this compression has a club structure, not a match structure. Club identity explains 56% of the squared directional residual. A generic scale term explains 29%. When the model has club effects, the scale term goes to zero. Across clubs, the club effect increases with mean Quality a little more steeply than generic compression predicts. Within a club, a change of Quality from season to season has no market residual at all. The market gives persistent strong clubs a higher level than M7 and persistent weak clubs a lower level.
3. Club residuals are persistent and predict later disagreement. The correlation of club-season effects is 0.77 one season later and 0.69 three seasons later. Club effects from the two previous seasons explain 21–57% of the residual variance in a new season.
4. Posterior state uncertainty is not a material cause. It removes 4% of the squared residual and about 9% of the favourite gap for strong favourites.
5. xG moves M7 away from the market for clubs with a persistent gap between goals and xG. The trailing goal-minus-xG gap explains most of the M2−M7 direction difference (correlation 0.72). The market is about 40% of the distance from M7 to M2 on this axis. Manchester City, Arsenal and Aston Villa score more than their xG. Crystal Palace, Bournemouth, Brentford and Wolves score less. This is part of the club structure, not all of it.
6. The market residual predicts later M7 Quality movement in the same direction, but M7 closes only about 14% of the gap in 19 matches. The residual autocorrelation is 0.28 at 38 matches and 0.29 at 76 matches. Slow adaptation is real, but most of the residual is persistent, not transient.
7. Home advantage and matchday personnel are secondary. Each changes the squared residual by about 2% or less.
8. The market advantage is concentrated. Matches with a disagreement of at least 10 pp are 14% of matches and give 62% (2016–2026) to 75% (2023–2026) of the total market advantage. When the largest 5% of market-favouring matches are removed, M7 is equal to the market or slightly better.
9. The experiment that the evidence supports first is a change to the Quality dynamics that makes persistent club strength less mean-reverting. Section 10 gives the pilot result.

## 1. Data and method

- Population: Premier League matches from 2016/17 to 16 September 2026. The primary window is 2023/24–2025/26, which is the product scoreboard: 1,140 matches. The extended window adds 2016/17–2022/23 (2,660 matches) and the 40 finished matches of 2026/27.
- M7 and M2 are the product models of `configs/product.toml` at `c7d94c7`. Each refits every match day with the results before that day. The runner reproduces the published scoreboard exactly: M7 0.97830, M2 0.98039, market 0.96502 and closing market 0.95973 log loss.
- The market is the Football-Data average pre-closing price with proportional de-vigging. Before 2019/20, Football-Data gives only the BetBrain average, and the analysis uses that family. The slopes do not change between the two families (1.24–1.28 before 2019, 1.16–1.22 after).
- The rolling forecasts are structural. They have no matchday-squad adjustment. The personnel analysis uses the archived history-only hindcast shift of the `research-personnel-measurement` branch.
- Directional strength is ln(p_home / p_away). The directional residual is market minus M7. A club effect is the coefficient of a design with +1 for the home club and −1 for the away club, so it is adjusted for the opponent. The ridge penalty is 2.
- Information advantage is ln(p_market(outcome) / p_M7(outcome)). Positive values favour the market. Intervals resample 28-day blocks within seasons.
- The certainty-equivalent (CE) forecast uses the same posterior mean log rates of each specification, with no Gaussian state uncertainty. It keeps the mixture of the three chance probabilities.

All results are retrospective. The M7 specification was developed on the same seasons. Results and xG are assumed available on the day after each match.

## 2. The shape of the disagreement

| Window | Matches | M7 | CE | M2 | Market | Median TV | 90th percentile TV |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2016–2023 | 2,660 | 0.95687 | 0.95641 | 0.96179 | 0.94645 | 4.9 pp | 10.5 pp |
| 2023–2026 | 1,140 | 0.97830 | 0.97739 | 0.98039 | 0.96502 | 5.0 pp | 11.2 pp |
| 2026/27 to date | 40 | 1.06789 | 1.06535 | 1.01533 | 1.04537 | 7.0 pp | 11.6 pp |

The draw difference is 18% of the total-variation distance. The disagreement is mostly about direction.

## 3. Question 1: global compression or club residuals

### Compression is real

| Regression of market directional log-odds | 2016–2026 slope | Range of season slopes |
| --- | ---: | --- |
| on M7 | 1.22 | 1.16–1.28 |
| on CE M7 | 1.20 | 1.14–1.26 |
| on M2 | 1.06 | 1.01–1.30 |
| closing market on M7 (2019–2026) | 1.20 | 1.14–1.23 |

Noise in M7 would bias this slope down, not up. The reverse regression gives an even larger scale, 1.32.

The outcomes give the same result without the market. The log-loss-optimal power on M7 directional odds, with the draw probability fixed, is 1.27 over 2016–2026, and it is above 1 in 9 of 10 full seasons. For the market it is 1.04. A stretch fitted only on earlier seasons improves M7 log loss in 7 of 9 seasons, by 0.0020 on average and by 0.0047 without the two seasons of empty stadiums (2019/20 and 2020/21). See `outcome_stretch.csv` and `outcome_experiments.csv`.

### The market disagreement has a club structure

| Terms for the directional residual, 2016–2026 | Scale coefficient | Explained share |
| --- | ---: | ---: |
| venue | — | 0.3% |
| venue + scale | +0.219 | 28.7% |
| venue + clubs | — | 55.5% |
| venue + scale + clubs | −0.021 | 55.7% |
| venue + scale + club-seasons | +0.052 | 71.4% |

The 2023–2026 window gives the same pattern: scale 22%, clubs 57%, and a scale coefficient of −0.07 with clubs.

Club identity and strength are confounded, because strong clubs are always favourites. `strength_structure.csv` separates the two with 200 club-seasons:

| Slope of club-season effect on mean M7 Quality | Value |
| --- | ---: |
| Between clubs, all | 0.86 |
| Between clubs, continuing clubs | 1.11 |
| Within a club, season to season | 0.01 |
| Generic compression at β = 1.2 predicts | 0.68 |

Generic compression predicts the same slope between and within clubs. The data show a between-club slope above that prediction and a within-club slope of zero. When M7 moves a club up or down from one season to the next, the market moves in the same direction by the same amount. It does not add the extra stretch. The extra stretch belongs to the long-run level of the club.

Answer: the apparent favourite compression is mostly the result of persistent club-level differences. M7 holds persistent strong clubs too close to the league mean, and also persistent weak clubs. A generic scale factor summarizes this because strong clubs are usually favourites.

One limit: the outcomes cannot yet separate the two forms. A chronological fit with separate terms for the trailing three-season Quality level and for the deviation from it gives similar coefficients for the two terms. It improves M7 less reliably than the plain stretch (5 of 9 seasons). The club structure is clear in the market data. The outcome data support under-scaling but are too noisy to show where it comes from.

## 4. Question 2: M2

| Diagnostic | M7 | M2 |
| --- | ---: | ---: |
| Market slope, 2016–2026 | 1.22 | 1.06 |
| Optimal outcome stretch, 2016–2026 | 1.27 | 1.09 |
| Explained share, venue + scale | 28.7% | 3.1% |
| Explained share, venue + clubs | 55.5% | 32.7% |
| Club-season effect correlation, one season later | 0.77 | 0.56 |
| Club-season effect correlation, three seasons later | 0.69 | 0.30 |
| Correlation of M7 and M2 club effects, 2023–2026 | 0.79 | |

M2 is not compressed, but it has club residuals that point the same way as those of M7. M2 residuals are less persistent. M2 uses a 1,095-day window with a 365-day half-life and has no mean reversion to zero, so it keeps more of the club level. The shared club residual shows information that neither performance model has. The larger and more persistent residual of M7 shows that M7 also pulls club levels toward the mean.

Club table, 2023–2026 (`clubs.csv`). Adjusted effects are opponent-adjusted log-odds with a scale term. Raw values are the mean club win probability difference. Goals minus xG is the 2023–2026 sum for attack plus defence.

| Club | Adjusted market − M7 | Adjusted market − M2 | Raw market − M7 win pp | Raw M7 − M2 win pp | Seasons with same sign | Goals minus xG |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| Brentford | −0.25 | −0.16 | −6.2 | +1.6 | 3/3 | −10.0 |
| Crystal Palace | −0.25 | −0.10 | −5.9 | +3.6 | 3/3 | −25.0 |
| Wolves | −0.16 | −0.15 | −2.8 | +1.3 | 3/3 | −12.3 |
| Everton | −0.09 | +0.05 | −2.7 | +4.3 | 3/3 | −0.6 |
| Bournemouth | −0.08 | +0.22 | −2.8 | +6.5 | 2/3 | −15.7 |
| Nottingham Forest | −0.06 | +0.03 | −2.0 | +2.2 | 3/3 | +9.0 |
| Newcastle | +0.01 | +0.09 | −2.2 | 0.0 | 2/3 | +1.9 |
| Brighton | +0.04 | +0.16 | −1.0 | +2.0 | 2/3 | −8.4 |
| Tottenham | +0.17 | +0.03 | +1.9 | −4.2 | 2/3 | +14.7 |
| Aston Villa | +0.18 | +0.11 | +1.7 | −2.2 | 2/3 | +24.0 |
| Manchester United | +0.25 | +0.28 | +3.5 | +0.7 | 3/3 | +6.5 |
| Chelsea | +0.28 | +0.44 | +3.1 | +2.4 | 3/3 | −10.1 |
| Liverpool | +0.34 | +0.39 | +3.6 | −2.0 | 3/3 | −1.3 |
| Arsenal | +0.40 | +0.44 | +4.1 | −2.8 | 3/3 | +28.4 |
| Manchester City | +0.53 | +0.40 | +6.9 | −6.5 | 3/3 | +38.2 |

The one-season clubs in 2023–2026 (Sheffield United, Luton, Leicester, Ipswich, Southampton) all have negative effects from −0.13 to −0.31. Sunderland and Leeds in 2025/26 are close to zero.

Groups, by the adjusted M2 − M7 difference (positive: M2 values the club higher than M7):

- M2 and M7 agree within 0.05, and the market differs from both in the same direction: Wolves, Manchester United, Liverpool, Arsenal, West Ham. The missing information for these clubs is outside both performance models.
- M7 values the club higher than M2 by at least 0.09: Sheffield United, Brentford, Crystal Palace, Everton, Bournemouth, Nottingham Forest, Leeds, Brighton, Chelsea. Seven of the nine scored fewer goals than their xG in 2023–2026. Everton and Nottingham Forest are the exceptions. For Brentford, Crystal Palace and Everton the market is below both models.
- M7 values the club lower than M2 by at least 0.09: Tottenham and Manchester City, which scored more goals than their xG (+14.7 and +38.2), and Luton, Leicester, Burnley and Sunderland. For the four promoted clubs, M2 gives an unseen club the league average, so M2 is not a useful control there.

## 5. Question 3: posterior uncertainty

| Measure, 2023–2026 | Value |
| --- | ---: |
| Mean absolute directional change from state integration | 0.013 |
| Mean absolute directional residual | 0.306 |
| Share of squared residual removed by CE | 3.8% |
| Market slope, full M7 → CE | 1.202 → 1.180 |
| Share of favourite gap from uncertainty, M7 favourite 0.55–0.65 | 4% |
| Share of favourite gap from uncertainty, M7 favourite ≥ 0.65 | 9% |
| Log loss CE − M7 | −0.0009 |

The SD of the log-rate difference is about 0.21. The integration effect is largest in the first match of a club (0.018) and for entrants (0.021), but it is still small there. H3 is rejected as a main mechanism. A change to state uncertainty for match forecasts is not justified by this evidence, and the season simulation needs that uncertainty.

## 6. Question 4: persistence out of sample

Correlation of club-season effects (`season_persistence.csv`):

| Season lag | Pairs | Correlation | Same sign | Quality-adjusted correlation |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 153 | 0.77 | 78% | 0.45 |
| 2 | 133 | 0.76 | 83% | 0.35 |
| 3 | 111 | 0.69 | 73% | 0.10 |

Explained share of the residual in a new season, with effects fitted on the two previous seasons (`predictive_persistence.csv`):

| Test season | Venue + scale | Venue + clubs |
| --- | ---: | ---: |
| 2018/19 | 0.49 | 0.57 |
| 2019/20 | 0.31 | 0.37 |
| 2020/21 | 0.22 | 0.46 |
| 2021/22 | 0.29 | 0.30 |
| 2022/23 | 0.20 | 0.21 |
| 2023/24 | 0.24 | 0.44 |
| 2024/25 | 0.23 | 0.30 |
| 2025/26 | 0.14 | 0.51 |
| 2026/27 (40 matches) | 0.21 | 0.48 |

Answer: yes. A known M7 club residual predicts the next market disagreement, and better than a generic scale. The part of the effect that the club's Quality does not explain persists for about two seasons.

A diagnostic uses the market only through earlier seasons. It adds the prior-season market club effects to M7 and fits their weight on earlier outcomes. It improves log loss in 4 of 8 seasons, by 0.0013 on average. Thus the persistent club residual is partly information about outcomes and partly a stable market view that outcomes do not confirm. This test cannot separate the two.

## 7. Question 7: xG

| Relation, 2016–2026 | Coefficient on trailing goal-minus-xG gap | Correlation |
| --- | ---: | ---: |
| M2 − M7 direction | 0.69 | 0.72 |
| Market − M7 direction | 0.27 | 0.40 |
| Market − M2 direction | −0.42 | −0.22 |

The trailing gap is the mean of attack plus defence goal-minus-xG over the previous 38 matches of the club. The market is between the two models. It treats about 40% of the gap as signal. The goal-minus-xG gap persists weakly. The correlation over the next 38 matches is 0.26 for the total, 0.24 for attack and 0.11 for defence.

A term on the trailing gap, fitted on earlier seasons, improves M7 log loss in 7 of 9 seasons, but only by 0.0002 on average. A blend toward M2 direction gives a similar result.

Answer: yes. xG pushes a recognizable set of clubs away from the market. These are clubs with persistent over-performance (City, Arsenal, Villa, Tottenham) or under-performance (Palace, Bournemouth, Brentford, Wolves) relative to xG. The outcome gain from a crude correction is small. The effect explains the M7-specific part of the club structure. It does not explain the part that M2 shares.

## 8. Questions 5 and 6: adaptation and structural change

Later change in M7 Quality, net of the M7 expected mean reversion, per unit of current club-perspective market residual (`adaptation.csv`):

| Horizon | All clubs | Share of residual closed | Entrants | Share closed |
| ---: | ---: | ---: | ---: | ---: |
| 1 match | 0.007 | 2% | 0.009 | 3% |
| 5 matches | 0.016 | 5% | 0.023 | 8% |
| 10 matches | 0.026 | 9% | 0.034 | 11% |
| 19 matches | 0.040 | 14% | 0.049 | 16% |

The standard errors are small (0.003 at 19 matches, naive), so the relation is not noise. The market sees some strength changes before M7 does. But the residual autocorrelation is 0.41 at lag 1, 0.33 at lag 19, 0.28 at lag 38 and 0.29 at lag 76. Most of the residual does not decay.

Entering clubs:

| Club match in season | Continuing clubs mean residual | Entrants mean residual |
| --- | ---: | ---: |
| 1 | +0.03 | −0.16 |
| 2–5 | +0.01 | −0.09 |
| 6–10 | +0.02 | −0.08 |
| 11–20 | +0.02 | −0.10 |
| 21–38 | +0.02 | −0.12 |

The market values entering clubs lower than M7 for the whole season, and the gap does not close. In 2023–2026, entrant matches gave 51% of the market advantage (information advantage 0.025, interval 0.011 to 0.039). In 2016–2026 this concentration is not present: 0.010 for entrant matches and 0.012 for other matches. A fixed entrant offset fitted on earlier seasons is not stable. It fails in 2025/26, when the market already valued Leeds and Sunderland close to M7. The market view of entrants is club-specific. That is consistent with squad investment information that M7 does not have.

Disagreements of 10 pp or more are not concentrated in entrant matches (18% of them, against 28% of other matches). They are only slightly more common early in the season (18% within the first five matches of a club, against 13%).

Answer to question 6: large disagreements are not mainly an adaptation problem. The early and entrant effects exist, but the largest disagreements come from persistent club residuals.

## 9. Question 8: home advantage and personnel

Home advantage (`home_advantage.csv`, `decomposition.csv`):

- The venue term is between −0.06 and +0.06 log-odds, depending on the terms and the season. It explains less than 1% of the squared residual.
- The market slope is 1.18 for M7 home favourites and 1.20 for M7 away favourites. The away-favourite intercept is −0.05.
- For near-even matches, M7 is too favourable to the home club in 2023/24 (−0.13 ± 0.03), but not in 2024/25 or 2025/26.
- M7 home advantage in the rate is about 0.19. This is about 0.33 in directional log-odds and 6–7 pp of home win probability in an even match. In the current case studies, home advantage decides the favourite. The market residual does not show that the home advantage is systematically wrong.

Matchday personnel, 2023–2026 (`personnel.csv`):

| Shift | Mean absolute directional shift | Correlation with residual | Moves toward market | Change in squared residual |
| --- | ---: | ---: | ---: | ---: |
| History-only hindcast | 0.076 | 0.17 | 57% | −2.1% |
| Realized-squad oracle | 0.139 | 0.18 | 55% | +4.5% |

The personnel shift moves toward the market a little more often than not, but it is a quarter of the residual in size. In matches with a disagreement of at least 10 pp, it is 0.087 against a residual of 0.70. Large residuals exist before the personnel adjustment and stay after it.

## 10. Question 9: the large disagreements

Information advantage by total-variation distance (`scoring.csv`, `scoring_2016_2026.csv`):

| Distance | 2023–2026 matches | Advantage [95% interval] | Outcome position | 2016–2026 matches | Advantage [95% interval] | Outcome position |
| --- | ---: | --- | ---: | ---: | --- | ---: |
| < 5 pp | 570 | −0.003 [−0.010, 0.005] | 0.09 | 1,920 | 0.002 [−0.002, 0.005] | 0.76 |
| 5–10 pp | 411 | 0.013 [−0.002, 0.027] | 0.97 | 1,404 | 0.009 [0.000, 0.017] | 0.84 |
| 10–15 pp | 136 | 0.071 [0.031, 0.112] | 1.49 | 407 | 0.049 [0.025, 0.075] | 1.19 |
| 15+ pp | 23 | 0.074 [−0.040, 0.194] | 1.03 | 69 | 0.095 [0.000, 0.179] | 1.14 |

The outcome position is 0 when the mean outcome agrees with the expectation under M7 and 1 when it agrees with the expectation under the market. Above 10 pp, the outcomes are at least as extreme as the market expects. In these cases the outcomes support the market, and the interval for 10–15 pp excludes zero in both windows.

The 10+ pp cases (2023–2026, 159 matches) are different from the rest in these ways:

| Property | 10+ pp | Under 10 pp |
| --- | ---: | ---: |
| Market more extreme than M7 | 67% | 64% |
| Favourite differs | 18% | 7% |
| Away favourite in market | 46% | 36% |
| Mean absolute finishing gap | 0.32 | 0.27 |
| Mean SD of the log-rate difference | 0.206 | 0.206 |
| Mean absolute personnel shift | 0.087 | 0.075 |
| Entrant match | 18% | 28% |
| A club within its first five matches | 18% | 13% |

Clubs in the most 10+ pp cases: Crystal Palace 35, Brentford 32, Manchester City 32, Tottenham 27, Manchester United 21, Arsenal 16, Chelsea 15, Liverpool 15.

State uncertainty does not separate these cases. Club identity does: the large cases are the persistent club residuals of Section 4, often with an away favourite whose level the market sets higher. Without the largest 5% of market-favouring matches, the mean advantage is −0.0004 in 2023–2026 and −0.0022 in 2016–2026. M7 is competitive in most matches. The net market advantage comes from these club-driven cases, which Section 6 shows are predictable before the match.

## 11. Current case studies

M7 unadjusted forecasts at the 17 September 2026 cutoff match the live forecast. No market quote for this round is in the corpus, so the "club-effect prediction" column applies the 2019–2026 historical club effects to M7. It is not a market price.

| Fixture | M7 H/D/A | CE | Neutral venue CE | M2 | Personnel adjusted | Club-effect prediction |
| --- | --- | --- | --- | --- | --- | --- |
| Brentford v Chelsea | 43/23/34 | 43/23/34 | 36/25/39 | 41/23/36 | 49/22/28 | 34/23/44 |
| Brighton v Arsenal | 30/25/44 | 30/26/44 | 25/26/49 | 23/25/53 | 27/25/48 | 25/25/50 |
| Bournemouth v Liverpool | 42/24/35 | 41/24/35 | 35/25/40 | 35/24/41 | 43/24/33 | 33/24/43 |
| Manchester City v Sunderland | 66/19/14 | 66/20/14 | 59/23/18 | 66/21/13 | 63/21/17 | 70/19/10 |

Quality (SD) at the cutoff: Brentford 0.077 (0.081), Chelsea 0.102 (0.081), Brighton 0.137, Arsenal 0.347, Bournemouth 0.082, Liverpool 0.124, Manchester City 0.265, Sunderland −0.094 (0.083).

- Brentford v Chelsea. M7 rates the two clubs almost equal. Home advantage makes Brentford the favourite. Uncertainty has no effect. Personnel moves the forecast further toward Brentford (shift +0.092). M2 also makes Brentford a narrow favourite. The historical residuals of both clubs point the other way: Brentford −0.26 and Chelsea +0.26. In the first four 2026/27 matches Chelsea has +0.52, and Brentford is close to zero. Chelsea scored 10 goals fewer than xG in 2023–2026, so xG does not explain the Chelsea residual. This case is a persistent club-level difference, made decisive by home advantage and personnel.
- Bournemouth v Liverpool. M7 Liverpool Quality fell from 0.316 at the start of 2025/26 to 0.124. M2 favours Liverpool. Bournemouth's goals were 15.7 below xG in 2023–2026, so xG raises Bournemouth in M7. The historical residuals are Bournemouth −0.12 and Liverpool +0.34, and both continue in 2026/27 (−0.31 and +0.45). The cause is a combination: xG over-values Bournemouth, the market keeps Liverpool's level while M7 follows the 2025/26 decline, and home advantage decides the favourite. Uncertainty has no effect.
- Brighton v Arsenal. M2 is more extreme than M7 toward Arsenal. Arsenal's goals exceed xG (+28), so xG holds Arsenal down in M7. Personnel moves toward Arsenal.
- Manchester City v Sunderland. Uncertainty integration changes City by 0.2 pp, so this is not an uncertainty case. M2 gives the same City probability as M7. The historical City effect (+0.40) predicts about 70%. Personnel moves the forecast away from City (63%). City has the largest goal-over-xG total (+38). This case is the persistent level of a strong club together with finishing that M7 treats as noise.

## 12. Question 10: model experiments

The standard for each experiment is a chronological improvement on outcomes, without market imitation. Pilot results from this study are in `outcome_experiments.csv`. They adjust M7 probabilities after the fact, so they are proxies for model changes, not model changes.

| Experiment | Hypothesis | Pilot evidence | Recommendation |
| --- | --- | --- | --- |
| Less mean reversion of Quality, or a hierarchical long-run club level | H1 and H2: M7 pulls persistent club strength toward the league mean | Directional stretch improves 7 of 9 seasons (−0.0020; −0.0047 without 2019–21). Market structure points to the persistent level. Section 13 gives the dynamics pilot. | Do first |
| External preseason squad-strength prior (squad value, wage bill or player ratings) | H2: missing squad information, especially for entrants and clubs such as Chelsea and Brentford | Club residuals persist and are shared with M2. Fixed entrant offset is not stable. Prior market club effects improve only 4 of 8 seasons. | Do second. It needs a source with historical timestamps. |
| Persistent finishing skill in the observation model (a club term for goals given xG) | H4 | Market treats 40% of the goal-minus-xG gap as signal. Persistence is 0.26. A crude trailing term gives +0.0002 average gain. | Do after the dynamics test, and only as a structural term, not a trailing adjustment |
| Faster Quality evolution | H5 | Market residual predicts Quality movement, but only 14% closes in 19 matches, and most residual is persistent | Do not do alone. Test it together with the first experiment, because a larger innovation SD also reduces the pull toward the mean. |
| Less state uncertainty | H3 | 4% of the squared residual; CE gains 0.0009 | Do not do |
| Change home advantage | H6 | Under 1% of the squared residual, not stable in sign | Do not do |
| Change the personnel adjustment | H7 | 2% of the squared residual, moves toward the market 57% of the time | Do not do in this workstream. Keep the prospective review. |

## 13. Pilot: Quality dynamics

PENDING

## Reproduce

```sh
uv run python scripts/research/market_disagreement_rolling.py --output runs/market-disagreement/rolling
uv run python scripts/research/market_disagreement_rolling.py --start 2016-08-01 --end 2023-08-01 --output runs/market-disagreement/rolling-early
uv run python scripts/research/market_disagreement_cases.py --output runs/market-disagreement/cases
cd scripts/research && uv run --with pandas python market_disagreement_analysis.py
```

The analysis script also needs three exports in `runs/market-disagreement/evidence/`. `match_xg.json` is `analysis.team_match_xg` for Premier League matches from July 2014. `betbrain_odds.json` is the `betbrain_average_preclosing` family for 2016/17–2018/19. Both come from the query-football-data helper. `chronological.csv` is `research/evidence/personnel-measurement/68cba95/pm-hindcast-report/chronological.csv` in `page324-data`.
