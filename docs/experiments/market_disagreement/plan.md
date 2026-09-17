# Plan: root causes of M7–market disagreement

This is a model-understanding study. It does not change M7, and it does not try to make M7 copy the market.

| Item | Value |
| --- | --- |
| Branch | `research-market-disagreement` |
| Main base | `c7d94c7` |
| Start date | 17 September 2026 |
| Claim level | Retrospective development evidence. The M7 specification was developed on the same seasons. |

## Population and information

- Premier League matches from 1 August 2023 to 16 September 2026: 1,140 matches in 2023/24–2025/26 and the finished matches of 2026/27.
- M7 and M2 are the product models of `configs/product.toml`. Each refits every match day with results before that day. Results and xG are assumed available on the day after the match.
- The market is the Football-Data average pre-closing price, de-vigged by proportional scaling. The closing price is kept for a sensitivity check. Historical quote times are not available.
- The rolling forecasts are structural: they have no matchday-squad adjustment. The personnel stage is measured only on the live forecasts of 2026/27, where the unadjusted and adjusted stages exist.
- No current market quote for the next Premier League round exists in the corpus. Case studies use the model decomposition and do not invent market values.

## Hypotheses and discriminating analyses

| Hypothesis | Analysis | Result that supports it | Result that rejects it |
| --- | --- | --- | --- |
| H1 generic compression | Regress market directional strength log(p_home/p_away) on the M7 value, then add club effects | Slope β well above 1, stable by season, and it stays after club effects | β falls close to 1 when club effects enter |
| H2 persistent club misvaluation | Opponent- and venue-adjusted club effects; fit on earlier seasons and test on a later season | Club effects predict the sign and size of later residuals | Out-of-sample correlation near zero |
| H3 state uncertainty flattening | Certainty-equivalent forecast from the same posterior means | CE removes a large share of the slope gap | CE changes little |
| H4 xG signal | The same analyses for M2 (goals only) | Club residuals differ between M2 and M7 in a pattern tied to goal−xG gaps | M2 and M7 residuals match |
| H5 slow adaptation | Market residual now against later change in M7 Quality | Residual predicts later Quality movement in its direction; residuals decay | No predictive relation |
| H6 home advantage | Venue terms in the regression, split by strength gap | Material home intercept | Intercept near zero |
| H7 personnel | Unadjusted, adjusted and market-direction in 2026/27 live forecasts | Adjustment moves M7 toward the market | Adjustment is small or moves away |

## Scoring

Information advantage for each match is ln(p_market(outcome) / p_M7(outcome)). Group it by disagreement size and by the candidate predictors. Uncertainty for club-level quantities uses resampling of club-seasons or match rounds, not independent matches.

## Stop or redirect

- If club effects fitted on earlier seasons do not predict later residuals (correlation below 0.2 and sign agreement below 60%), stop treating club identity as a mechanism.
- If the certainty-equivalent forecast removes less than a quarter of the slope gap, do not propose an uncertainty experiment on match evidence alone.
- A model experiment is justified only if it names a missing mechanism and can be scored on outcomes without the market.
