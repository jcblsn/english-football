# Root causes of M7–market disagreement

Status: retrospective development evidence, 17 September 2026. Branch: `research-market-disagreement`. Main base: `c7d94c7`. The plan is in [plan.md](plan.md). The tables are in [tables/](tables/).

## Terms

- Directional strength: ln(p_home / p_away) for one forecast.
- Residual: the market directional strength minus the M7 directional strength. A positive residual means that the market gives the home club more strength than M7 gives.
- Compression: M7 directional strengths that are too near zero.
- Club effect: the coefficient of a club in a regression of the residual. The design is +1 for the home club and −1 for the away club. Thus the club effect includes an adjustment for the opponent. The ridge penalty is 2.
- Scale term: a term that makes the residual proportional to the M7 directional strength. A generic compression gives a positive scale term.
- Information advantage: ln(p_market(outcome) / p_M7(outcome)). A positive value is an advantage for the market.
- CE forecast: the certainty-equivalent forecast. It uses the posterior mean log rates of each M7 specification without the Gaussian state uncertainty. It keeps the mixture of the three chance probabilities.
- Entrant: a club that did not play in the Premier League in the previous season.

## Summary

1. M7 makes the strength differences between teams too small. In each of ten seasons, the market directional strength is approximately 1.2 times the M7 value. The outcomes show the same result without the market. The best power on the M7 directional odds is 1.27 in 2016–2026. For the market it is 1.04, and for M2 it is 1.09.
2. The compression has a club structure. Club effects explain 56% of the squared residual. A scale term explains 29%. When the regression has club effects, the scale term decreases to zero. Between clubs, the club effect increases with mean Quality a little more than generic compression predicts. Within a club, a change of Quality from one season to the next gives no residual.
3. Thus the market gives a higher level than M7 to clubs that are strong for many seasons. It gives a lower level than M7 to clubs that are weak for many seasons.
4. Club effects continue from season to season, and they predict the residuals of later seasons. The correlation of club-season effects is 0.77 after one season and 0.69 after three seasons. Club effects from the two previous seasons explain 21–57% of the residual variance in a new season.
5. The posterior state uncertainty is not an important cause. It explains 4% of the squared residual. It explains approximately 9% of the difference in the probability of strong favourites.
6. xG moves M7 away from the market for clubs whose goals are different from their xG for many seasons. The previous goal-minus-xG gap explains most of the difference between the M2 and M7 directional strengths (correlation 0.72). On this gap, the market is approximately 40% of the distance from M7 to M2. Manchester City, Arsenal and Aston Villa score more goals than their xG. Crystal Palace, Bournemouth, Brentford and Wolves score fewer. This is one part of the club structure. It is not all of it.
7. The residual predicts a later change of M7 Quality in the same direction. But M7 closes only approximately 14% of the gap in 19 matches. The residual autocorrelation is 0.28 after 38 matches and 0.29 after 76 matches. Thus M7 adapts slowly, but most of the residual does not decrease with time.
8. Home advantage and the matchday personnel adjustment are secondary causes. Each explains 2% or less of the squared residual.
9. A small number of matches give most of the market advantage. Matches with a disagreement of 10 pp or more are 14% of all matches. They give 62% (2016–2026) to 75% (2023–2026) of the total market advantage. Without the 5% of matches with the largest market advantage, M7 is equal to the market or a little better.
10. The first experiment that the evidence supports is a change to the Quality dynamics. The change makes the Quality of a club return more slowly to the league mean. In a pilot, Quality is a random walk. The pilot decreases the M7 log loss by 0.0024 (95% interval −0.0034 to −0.0014) in 2016–2026, and it does not use the market. It decreases the market slope from 1.22 to 1.12. It removes approximately one third of the club effect of Manchester City, Arsenal and Liverpool. It does not change Brentford or Crystal Palace. Section 13 gives the details. It also gives the checks that the pilot does not include.

## 1. Data and method

- Population: Premier League matches from 2016/17 to 16 September 2026. The primary window is 2023/24–2025/26, with 1,140 matches. This is the population of the product scoreboard. The extended window adds 2016/17–2022/23 (2,660 matches) and the 40 finished matches of 2026/27.
- Models: M7 and M2 are the product models of `configs/product.toml` at `c7d94c7`. On each match day, each model fits again with the results before that day. The runner gives the published scoreboard values exactly: M7 0.97830, M2 0.98039, market 0.96502 and closing market 0.95973 log loss.
- Market: the Football-Data average pre-closing price. The de-vigging is proportional. Before 2019/20, Football-Data gives only the BetBrain average, and this study uses that family. The slopes of the two families are similar: 1.24–1.28 before 2019 and 1.16–1.22 after 2019.
- Personnel: the rolling forecasts have no matchday-squad adjustment. The personnel analysis uses the archived history-only hindcast shift of the `research-personnel-measurement` branch.
- Intervals: the intervals resample 28-day blocks in each season.

All results are retrospective. The M7 specification was developed on the same seasons. The study assumes that each result and its xG are available on the day after the match.

## 2. Shape of the disagreement

| Window | Matches | M7 | CE | M2 | Market | Median TV | 90th percentile TV |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2016–2023 | 2,660 | 0.95687 | 0.95641 | 0.96179 | 0.94645 | 4.9 pp | 10.5 pp |
| 2023–2026 | 1,140 | 0.97830 | 0.97739 | 0.98039 | 0.96502 | 5.0 pp | 11.2 pp |
| 2026/27 to date | 40 | 1.06789 | 1.06535 | 1.01533 | 1.04537 | 7.0 pp | 11.6 pp |

The difference in draw probability is 18% of the total-variation (TV) distance. Thus most of the disagreement is about direction.

## 3. Question 1: global compression or club effects

### The compression is real

| Regression of the market directional strength | 2016–2026 slope | Range of season slopes |
| --- | ---: | --- |
| on M7 | 1.22 | 1.16–1.28 |
| on CE M7 | 1.20 | 1.14–1.26 |
| on M2 | 1.06 | 1.01–1.30 |
| closing market on M7 (2019–2026) | 1.20 | 1.14–1.23 |

Noise in the M7 values decreases this slope. It cannot increase the slope. The reverse regression gives a larger scale, 1.32.

The outcomes give the same result without the market. The best power on the M7 directional odds, with a fixed draw probability, is 1.27 in 2016–2026. The power is more than 1 in 9 of 10 full seasons. For the market it is 1.04. We also fitted a stretch on earlier seasons only. This stretch decreases the M7 log loss in 7 of 9 seasons. The mean decrease is 0.0020. Without 2019/20 and 2020/21, when the stadiums were empty, the mean decrease is 0.0047. See `outcome_stretch.csv` and `outcome_experiments.csv`.

### The residual has a club structure

| Terms in the regression of the residual, 2016–2026 | Scale term | Explained share |
| --- | ---: | ---: |
| venue | — | 0.3% |
| venue + scale | +0.219 | 28.7% |
| venue + clubs | — | 55.5% |
| venue + scale + clubs | −0.021 | 55.7% |
| venue + scale + club-seasons | +0.052 | 71.4% |

The 2023–2026 window shows the same pattern. The scale term explains 22%, and club effects explain 57%. With club effects, the scale term is −0.07.

Club identity and club strength are not independent, because strong clubs are almost always favourites. `strength_structure.csv` separates the two with 200 club-seasons:

| Slope of the club-season effect on the mean M7 Quality | Value |
| --- | ---: |
| Between clubs, all clubs | 0.86 |
| Between clubs, continuing clubs | 1.11 |
| Within a club, from season to season | 0.01 |
| Value that generic compression at β = 1.2 predicts | 0.68 |

Generic compression predicts the same slope between clubs and within a club. The data show a different result. The slope between clubs is more than the predicted value, and the slope within a club is zero. When M7 moves a club up or down from one season to the next, the market moves the club in the same direction by the same quantity. The market does not add more stretch to this change. The additional stretch is on the long-term level of the club.

Answer: most of the apparent compression of favourites comes from long-term differences between clubs. M7 keeps clubs that are strong for many seasons too near the league mean. It also keeps clubs that are weak for many seasons too near the league mean. A generic scale term describes this pattern only because strong clubs are usually favourites.

Limit: the outcomes cannot yet separate the two forms. We fitted two terms on earlier seasons. One term is the mean Quality of the club in the previous three seasons. The other term is the difference from that mean. The two coefficients are similar. This fit decreases the M7 log loss in only 5 of 9 seasons, which is fewer than the simple stretch. The club structure is clear in the market data. The outcome data show that M7 makes differences too small, but the data have too much noise to show the source.

## 4. Question 2: M2

| Diagnostic | M7 | M2 |
| --- | ---: | ---: |
| Market slope, 2016–2026 | 1.22 | 1.06 |
| Best outcome stretch, 2016–2026 | 1.27 | 1.09 |
| Explained share, venue + scale | 28.7% | 3.1% |
| Explained share, venue + clubs | 55.5% | 32.7% |
| Correlation of club-season effects, after one season | 0.77 | 0.56 |
| Correlation of club-season effects, after three seasons | 0.69 | 0.30 |
| Correlation of M7 and M2 club effects, 2023–2026 | 0.79 | |

M2 has no compression. But M2 has club effects in the same direction as the M7 club effects. The M2 club effects change more from season to season. M2 uses a window of 1,095 days with a half-life of 365 days. It has no return to zero. Thus M2 keeps more of the long-term level of a club.

The club effects that M2 and M7 share show information that neither model has. The M7 club effects are larger and more stable. This shows that M7 also moves the level of a club toward the league mean.

The club table below is for 2023–2026 (`clubs.csv`). An adjusted effect is a club effect in log-odds, from a regression that also has a scale term. A raw value is the mean difference in the win probability of the club. Goals minus xG is the 2023–2026 sum for attack and defence.

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

In 2023–2026, five clubs played only one season: Sheffield United, Luton, Leicester, Ipswich and Southampton. All five have negative effects, from −0.13 to −0.31. The effects of Sunderland and Leeds in 2025/26 are near zero.

The groups below use the adjusted M2 − M7 difference. A positive difference means that M2 gives the club a higher value than M7 gives.

- M2 and M7 agree to within 0.05, and the market is different from both in the same direction: Wolves, Manchester United, Liverpool, Arsenal and West Ham. For these clubs, the missing information is outside both models.
- M7 gives the club a value at least 0.09 higher than M2 gives: Sheffield United, Brentford, Crystal Palace, Everton, Bournemouth, Nottingham Forest, Leeds, Brighton and Chelsea. Seven of these nine clubs scored fewer goals than their xG in 2023–2026. Everton and Nottingham Forest are the exceptions. For Brentford, Crystal Palace and Everton, the market value is lower than the values of both models.
- M7 gives the club a value at least 0.09 lower than M2 gives: Tottenham and Manchester City, which scored more goals than their xG (+14.7 and +38.2). Luton, Leicester, Burnley and Sunderland are also in this group. These four clubs were promoted, and M2 gives a club without history the league average. Thus M2 is not a good control for them.

## 5. Question 3: posterior uncertainty

| Measure, 2023–2026 | Value |
| --- | ---: |
| Mean absolute change of directional strength from state integration | 0.013 |
| Mean absolute residual | 0.306 |
| Share of the squared residual that the CE forecast removes | 3.8% |
| Market slope, full M7 → CE | 1.202 → 1.180 |
| Share of the favourite difference from uncertainty, M7 favourite 0.55–0.65 | 4% |
| Share of the favourite difference from uncertainty, M7 favourite ≥ 0.65 | 9% |
| Log loss, CE − M7 | −0.0009 |

The SD of the log-rate difference is approximately 0.21. The integration has its largest effect in the first match of a club (0.018) and for entrants (0.021). The effect is small there too.

Answer: posterior uncertainty is not a main cause. This evidence does not support a change to the state uncertainty of match forecasts. The season simulation also needs that uncertainty.

## 6. Question 4: persistence out of sample

Correlation of club-season effects (`season_persistence.csv`):

| Season lag | Pairs | Correlation | Same sign | Correlation after Quality adjustment |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 153 | 0.77 | 78% | 0.45 |
| 2 | 133 | 0.76 | 83% | 0.35 |
| 3 | 111 | 0.69 | 73% | 0.10 |

Explained share of the residual in a new season. The club effects come from the two previous seasons (`predictive_persistence.csv`):

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

Answer: yes. A known club effect predicts the next residuals of the club. It gives a better prediction than a generic scale term. The part of the club effect that the club Quality does not explain continues for approximately two seasons.

We also did a diagnostic test that uses the market of earlier seasons only. The test adds the previous club effects to M7 and fits their weight on earlier outcomes. It decreases the log loss in 4 of 8 seasons, and the mean decrease is 0.0013. Thus part of the club effect is information about outcomes. Another part is a stable market view that the outcomes do not confirm. This test cannot separate the two parts.

## 7. Question 7: xG

| Relation, 2016–2026 | Coefficient on the previous goal-minus-xG gap | Correlation |
| --- | ---: | ---: |
| M2 − M7 directional strength | 0.69 | 0.72 |
| Market − M7 directional strength | 0.27 | 0.40 |
| Market − M2 directional strength | −0.42 | −0.22 |

The previous gap is the mean goal-minus-xG value of the club for attack and defence in its previous 38 matches. The market is between the two models. It uses approximately 40% of the gap as information.

The gap continues only a little into the future. The correlation with the next 38 matches is 0.26 for the total, 0.24 for attack and 0.11 for defence. A term on the previous gap, fitted on earlier seasons, decreases the M7 log loss in 7 of 9 seasons. The mean decrease is only 0.0002. A blend toward the M2 directional strength gives a similar result.

Answer: yes. xG moves a specific set of clubs away from the market. Some of these clubs score more goals than their xG for many seasons: City, Arsenal, Villa and Tottenham. Others score fewer: Palace, Bournemouth, Brentford and Wolves. A simple correction gives only a small improvement on outcomes. This effect explains the part of the club structure that only M7 has. It does not explain the part that M2 also has.

## 8. Questions 5 and 6: adaptation and structural change

The table shows the later change of M7 Quality for each unit of the current club residual. The change does not include the return to the mean that M7 expects (`adaptation.csv`):

| Horizon | All clubs | Share of the residual that M7 closes | Entrants | Share that M7 closes |
| ---: | ---: | ---: | ---: | ---: |
| 1 match | 0.007 | 2% | 0.009 | 3% |
| 5 matches | 0.016 | 5% | 0.023 | 8% |
| 10 matches | 0.026 | 9% | 0.034 | 11% |
| 19 matches | 0.040 | 14% | 0.049 | 16% |

The standard errors are small (naive value 0.003 at 19 matches). Thus the relation is not noise. The market sees some changes of strength before M7 sees them. But the residual autocorrelation is 0.41 at lag 1, 0.33 at lag 19, 0.28 at lag 38 and 0.29 at lag 76. Most of the residual does not decrease with time.

Entrants:

| Club match in the season | Mean residual, continuing clubs | Mean residual, entrants |
| --- | ---: | ---: |
| 1 | +0.03 | −0.16 |
| 2–5 | +0.01 | −0.09 |
| 6–10 | +0.02 | −0.08 |
| 11–20 | +0.02 | −0.10 |
| 21–38 | +0.02 | −0.12 |

The market gives entrants a lower value than M7 gives for all of the season. The gap does not close. In 2023–2026, entrant matches gave 51% of the market advantage (information advantage 0.025, interval 0.011 to 0.039). In 2016–2026, this pattern does not occur: the value is 0.010 for entrant matches and 0.012 for other matches.

A fixed entrant offset, fitted on earlier seasons, is not stable. It fails in 2025/26. In that season, the market gave Leeds and Sunderland values near the M7 values. Thus the market view of an entrant is specific to the club. This agrees with information about squad investment, which M7 does not have.

Disagreements of 10 pp or more do not occur mostly in entrant matches. Entrant matches are 18% of these disagreements and 28% of the other matches. These disagreements occur only a little more frequently early in the season. A club is in its first five matches in 18% of these disagreements and in 13% of the other matches.

Answer to question 6: slow adaptation is not the main cause of large disagreements. The early-season effect and the entrant effect are real. But most large disagreements come from long-term club effects.

## 9. Question 8: home advantage and personnel

Home advantage (`home_advantage.csv`, `decomposition.csv`):

- The venue term is between −0.06 and +0.06 log-odds. The value changes with the regression terms and the season. The term explains less than 1% of the squared residual.
- The market slope is 1.18 when M7 makes the home club the favourite. It is 1.20 when M7 makes the away club the favourite. The intercept for away favourites is −0.05.
- In near-even matches, M7 gives the home club too much advantage in 2023/24 (−0.13 ± 0.03). It does not do this in 2024/25 or 2025/26.
- The M7 home advantage in the log rate is approximately 0.19. In an even match, this is approximately 0.33 of directional strength and 6–7 pp of home win probability. In the current case studies, home advantage decides the favourite. But the residuals do not show that the home advantage is wrong in a systematic way.

Matchday personnel, 2023–2026 (`personnel.csv`):

| Shift | Mean absolute shift of directional strength | Correlation with the residual | Moves toward the market | Change in squared residual |
| --- | ---: | ---: | ---: | ---: |
| History-only hindcast | 0.076 | 0.17 | 57% | −2.1% |
| Realized-squad oracle | 0.139 | 0.18 | 55% | +4.5% |

The personnel shift moves the forecast toward the market in a little more than half of matches. But the shift is only approximately one quarter of the residual. In matches with a disagreement of 10 pp or more, the mean shift is 0.087 and the mean residual is 0.70. Large residuals occur before the personnel adjustment, and they stay after it.

## 10. Question 9: large disagreements

Information advantage by total-variation distance (`scoring.csv`, `scoring_2016_2026.csv`):

| Distance | 2023–2026 matches | Advantage [95% interval] | Outcome position | 2016–2026 matches | Advantage [95% interval] | Outcome position |
| --- | ---: | --- | ---: | ---: | --- | ---: |
| < 5 pp | 570 | −0.003 [−0.010, 0.005] | 0.09 | 1,920 | 0.002 [−0.002, 0.005] | 0.76 |
| 5–10 pp | 411 | 0.013 [−0.002, 0.027] | 0.97 | 1,404 | 0.009 [0.000, 0.017] | 0.84 |
| 10–15 pp | 136 | 0.071 [0.031, 0.112] | 1.49 | 407 | 0.049 [0.025, 0.075] | 1.19 |
| 15+ pp | 23 | 0.074 [−0.040, 0.194] | 1.03 | 69 | 0.095 [0.000, 0.179] | 1.14 |

The outcome position is 0 when the mean outcome agrees with the M7 expectation. It is 1 when the mean outcome agrees with the market expectation. Above 10 pp, the outcomes are at least as extreme as the market expects. Thus the outcomes support the market in these matches. In both windows, the interval for 10–15 pp does not include zero.

The table compares the 159 matches of 10 pp or more in 2023–2026 with the other matches:

| Property | 10+ pp | Under 10 pp |
| --- | ---: | ---: |
| Market more extreme than M7 | 67% | 64% |
| Different favourite | 18% | 7% |
| Away favourite in the market | 46% | 36% |
| Mean absolute goal-minus-xG gap | 0.32 | 0.27 |
| Mean SD of the log-rate difference | 0.206 | 0.206 |
| Mean absolute personnel shift | 0.087 | 0.075 |
| Entrant match | 18% | 28% |
| A club in its first five matches | 18% | 13% |

Clubs with the most matches of 10 pp or more: Crystal Palace 35, Brentford 32, Manchester City 32, Tottenham 27, Manchester United 21, Arsenal 16, Chelsea 15 and Liverpool 15.

State uncertainty does not separate these matches from other matches. Club identity separates them. Most large disagreements come from the club effects of Section 4. Often the away club is the favourite, and the market gives it a higher level than M7 gives.

Without the 5% of matches with the largest market advantage, the mean advantage is −0.0004 in 2023–2026 and −0.0022 in 2016–2026. Thus M7 is equal to the market in most matches. The net market advantage comes from these club matches. Section 6 shows that these club effects are predictable before the match.

## 11. Current case studies

At the cutoff of 17 September 2026, the unadjusted M7 forecasts are the same as the live forecasts. The corpus has no market price for this round. Thus the column "Club-effect prediction" applies the 2019–2026 club effects to M7. It is not a market price.

| Fixture | M7 H/D/A | CE | CE at a neutral venue | M2 | After personnel adjustment | Club-effect prediction |
| --- | --- | --- | --- | --- | --- | --- |
| Brentford v Chelsea | 43/23/34 | 43/23/34 | 36/25/39 | 41/23/36 | 49/22/28 | 34/23/44 |
| Brighton v Arsenal | 30/25/44 | 30/26/44 | 25/26/49 | 23/25/53 | 27/25/48 | 25/25/50 |
| Bournemouth v Liverpool | 42/24/35 | 41/24/35 | 35/25/40 | 35/24/41 | 43/24/33 | 33/24/43 |
| Manchester City v Sunderland | 66/19/14 | 66/20/14 | 59/23/18 | 66/21/13 | 63/21/17 | 70/19/10 |

Quality (SD) at the cutoff: Brentford 0.077 (0.081), Chelsea 0.102 (0.081), Brighton 0.137, Arsenal 0.347, Bournemouth 0.082, Liverpool 0.124, Manchester City 0.265 and Sunderland −0.094 (0.083).

Brentford v Chelsea:

- M7 gives the two clubs almost equal Quality. Home advantage makes Brentford the favourite. Uncertainty has no effect.
- The personnel adjustment moves the forecast more toward Brentford (shift +0.092). M2 also makes Brentford a small favourite.
- The club effects point in the opposite direction: Brentford −0.26 and Chelsea +0.26. In the first four matches of 2026/27, the Chelsea residual is +0.52, and the Brentford residual is near zero.
- Chelsea scored 10 goals fewer than its xG in 2023–2026. Thus xG does not explain the Chelsea effect.
- Cause: a long-term difference in club level. Home advantage and personnel make this difference change the favourite.

Bournemouth v Liverpool:

- The M7 Quality of Liverpool decreased from 0.316 at the start of 2025/26 to 0.124. M2 makes Liverpool the favourite.
- Bournemouth scored 15.7 goals fewer than its xG in 2023–2026. Thus xG increases the M7 value of Bournemouth.
- The club effects are Bournemouth −0.12 and Liverpool +0.34. Both continue in 2026/27 (−0.31 and +0.45).
- Cause: a combination of three effects. xG gives Bournemouth too high a value. The market keeps the level of Liverpool, but M7 follows the decrease of 2025/26. Home advantage decides the favourite. Uncertainty has no effect.

Brighton v Arsenal:

- M2 gives Arsenal more probability than M7 gives.
- Arsenal scored more goals than its xG (+28). Thus xG decreases the M7 value of Arsenal.
- The personnel adjustment moves the forecast toward Arsenal.

Manchester City v Sunderland:

- Uncertainty integration changes the City probability by 0.2 pp. Thus uncertainty is not the cause.
- M2 gives City the same probability as M7 gives.
- The City club effect (+0.40) predicts approximately 70%. The personnel adjustment moves the forecast away from City (63%).
- City has the largest goal-minus-xG total (+38).
- Cause: the long-term level of a strong club, and a goal-minus-xG gap that M7 treats as noise.

## 12. Question 10: model experiments

Each experiment must decrease the log loss on outcomes in a chronological test. It must not copy the market. The pilot results of this study are in `outcome_experiments.csv`. These pilots adjust the M7 probabilities after the forecast. Thus they are approximations of model changes. They are not model changes.

| Experiment | Hypothesis | Pilot evidence | Recommendation |
| --- | --- | --- | --- |
| Slower return of Quality to the mean, or a long-term club level in a hierarchical model | H1 and H2: M7 moves the long-term strength of clubs toward the league mean | The directional stretch decreases the log loss in 7 of 9 seasons (−0.0020; −0.0047 without 2019–21). The market data point to the long-term club level. The dynamics pilot of Section 13 decreases the log loss by 0.0024, and its interval is below zero. | Do this first, as a full experiment with season panels. |
| External preseason prior for squad strength (squad value, wage bill or player ratings) | H2: missing squad information, mostly for entrants and for clubs such as Chelsea and Brentford | Club effects continue from season to season, and M2 has them too. A fixed entrant offset is not stable. Previous club effects decrease the log loss in only 4 of 8 seasons. | Do this second. It needs a source with historical timestamps. |
| A club finishing term in the observation model (goals given xG) | H4 | The market uses 40% of the goal-minus-xG gap. The correlation with the next 38 matches is 0.26. A simple term on the previous gap decreases the log loss by only 0.0002. | Do this after the dynamics experiment. Use a structural term, not an adjustment from previous values. |
| Faster Quality evolution | H5 | The residual predicts later Quality change, but M7 closes only 14% in 19 matches. Most of the residual does not decrease. | Do not do this alone. Test it with the first experiment, because a larger innovation SD also decreases the return to the mean. |
| Less state uncertainty | H3 | 4% of the squared residual. The CE forecast decreases the log loss by 0.0009. | Do not do this. |
| A different home advantage | H6 | Less than 1% of the squared residual. The sign is not stable. | Do not do this. |
| A different personnel adjustment | H7 | 2% of the squared residual. The shift moves toward the market in 57% of matches. | Do not do this in this workstream. Keep the prospective review. |

## 13. Pilot: Quality dynamics

This pilot tests H1 against H2 with a model change, not with a probability adjustment. It changes one value of the M7 dynamics: the annual Quality retention. The pilot does not change the innovation SD (0.09), the Tilt dynamics, the observation model, the entry priors or the specification mixture. On each match day, each run fits again from the start of the history, the same as the control. The runner option is `--quality-retention`. The tables are `dynamics_pilot_summary.csv`, `dynamics_pilot_seasons.csv` and `dynamics_pilot_clubs.csv`.

| Quality retention | 2016–2026 log loss | Score NLL | Market slope | Best outcome stretch | Squared residual | Scale share | Club share |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.85 (product) | 0.96330 | 2.92674 | 1.22 | 1.27 | 0.150 | 29% | 56% |
| 0.95 | 0.96156 | 2.92499 | 1.15 | 1.21 | 0.126 | 18% | 46% |
| 1.00 | 0.96090 | 2.92445 | 1.12 | 1.17 | 0.118 | 12% | 42% |

Candidate minus control, 3,800 matches, 2016/17–2025/26:

| Quality retention | Log loss [95% interval] | Score NLL | Seasons with a lower log loss | Entrant matches | Other matches |
| ---: | --- | ---: | ---: | ---: | ---: |
| 0.95 | −0.0017 [−0.0024, −0.0010] | −0.0018 | 8 of 10 | −0.0020 | −0.0016 |
| 1.00 | −0.0024 [−0.0034, −0.0014] | −0.0023 | 8 of 10 | −0.0027 | −0.0023 |

The log loss increases in two seasons: 2020/21 (+0.0001) and 2022/23 (+0.0010). In 2025/26, the log loss does not change (−0.0002), and the score NLL increases a little (+0.0006). On the 40 matches of 2026/27, the random walk decreases the log loss by 0.0040. For comparison, the market log loss is 0.0133 lower than the M7 log loss in 2023–2026. The random walk closes approximately 18% of that gap (0.0023 of 0.0133).

Change of the club effect in 2023–2026, from the control to the random walk:

- Manchester City +0.45 → +0.32, Arsenal +0.31 → +0.20, Liverpool +0.27 → +0.16 and Chelsea +0.24 → +0.19.
- The promoted clubs move toward zero by 0.05–0.07.
- These clubs do not change: Brentford (−0.27 → −0.29), Crystal Palace (−0.26 → −0.26), Bournemouth (−0.09 → −0.09) and Manchester United (+0.24 → +0.22).

Interpretation:

- The return of Quality to zero is an important cause of the compression. The effect is on the long-term level of clubs at the top and bottom of the table, as Section 3 predicts. The outcome improvement does not use the market.
- It is not the only cause. The slope stays at 1.12, the best outcome stretch stays at 1.17, and club effects still explain 42% of the squared residual.
- The remaining club effects are for mid-table clubs. These clubs have a long-term goal-minus-xG gap or information outside both models: Brentford, Crystal Palace, Bournemouth, Wolves and Manchester United. The second and third experiments of Section 12 are for these clubs.

The pilot does not include the checks below. A full experiment must include them before a change to `main`:

- Season panels. A random walk increases the uncertainty of future season paths. Part of the evidence for M7 is its interval coverage. Thus the panels must show the effect on rank RPS, points CRPS and coverage in all four divisions.
- Joint dynamics. The pilot keeps the innovation SD at 0.09. The experiment must select the retention and the innovation SD together, with the chronological evidence of the specification mixture. It must make this selection on earlier seasons only.
- Other divisions and the entry priors. The entry priors read the fitted states of the source division.
- Selection. This study selected the pilot after it examined the same seasons. Thus the gain is retrospective development evidence. It needs a matched prospective record.

## Reproduce

```sh
uv run python scripts/research/market_disagreement_rolling.py --output runs/market-disagreement/rolling
uv run python scripts/research/market_disagreement_rolling.py --start 2016-08-01 --end 2023-08-01 --output runs/market-disagreement/rolling-early
uv run python scripts/research/market_disagreement_rolling.py --start 2016-08-01 --quality-retention 0.95 --output runs/market-disagreement/retention-0.95
uv run python scripts/research/market_disagreement_rolling.py --start 2016-08-01 --quality-retention 1.0 --output runs/market-disagreement/retention-1.0
uv run python scripts/research/market_disagreement_cases.py --output runs/market-disagreement/cases
cd scripts/research && uv run --with pandas python market_disagreement_analysis.py
```

The analysis script also needs three files in `runs/market-disagreement/evidence/`:

- `match_xg.json`: `analysis.team_match_xg` for Premier League matches from July 2014. Export it with the query-football-data helper.
- `betbrain_odds.json`: the `betbrain_average_preclosing` family for 2016/17–2018/19. Export it with the query-football-data helper.
- `chronological.csv`: the object `research/evidence/personnel-measurement/68cba95/pm-hindcast-report/chronological.csv` in `page324-data`.
