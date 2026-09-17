# Plan: root causes of M7–market disagreement

This study examines the M7 model. It does not change M7. It does not try to make M7 copy the market. We wrote this plan before the analysis.

| Item | Value |
| --- | --- |
| Branch | `research-market-disagreement` |
| Main base | `c7d94c7` |
| Start date | 17 September 2026 |
| Claim level | Retrospective development evidence. The M7 specification was developed on the same seasons. |

## Population and information

- Premier League matches from 1 August 2023 to 16 September 2026. These are the 1,140 matches of 2023/24–2025/26 and the finished matches of 2026/27.
- M7 and M2 are the product models of `configs/product.toml`. On each match day, each model fits again with the results before that day. We assume that each result and its xG are available on the day after the match.
- The market is the Football-Data average pre-closing price. The de-vigging is proportional. We keep the closing price for a sensitivity check. The historical quote times are not available.
- The rolling forecasts have no matchday-squad adjustment. We measure the personnel stage only on the live forecasts of 2026/27, which have the unadjusted and the adjusted stages.
- The corpus has no market price for the next Premier League round. The case studies use the model decomposition. They do not invent market values.

## Hypotheses and tests

Directional strength is ln(p_home / p_away).

| Hypothesis | Analysis | Result that supports the hypothesis | Result that rejects the hypothesis |
| --- | --- | --- | --- |
| H1: generic compression | Regress the market directional strength on the M7 value. Then add club effects. | The slope β is much more than 1 and stable in each season. It stays when the regression has club effects. | β decreases to near 1 when the regression has club effects. |
| H2: M7 gives some clubs a wrong value for many seasons | Club effects with adjustment for opponent and venue. Fit on earlier seasons and test on a later season. | Club effects predict the sign and size of later residuals. | The out-of-sample correlation is near zero. |
| H3: state uncertainty makes probabilities less extreme | The certainty-equivalent forecast from the same posterior means | The CE forecast removes a large part of the slope gap. | The CE forecast changes the result by a small quantity. |
| H4: xG signal | The same analyses for M2, which uses goals only | The M2 and M7 club residuals are different, and the difference follows the goal-minus-xG gaps. | The M2 and M7 residuals are the same. |
| H5: slow adaptation | The current residual against the later change in M7 Quality | The residual predicts a later Quality change in its direction, and the residuals decrease. | No relation |
| H6: home advantage | Venue terms in the regression, in groups by strength gap | A large home intercept | An intercept near zero |
| H7: personnel | The unadjusted forecast, the adjusted forecast and the market direction in the 2026/27 live forecasts | The adjustment moves M7 toward the market. | The adjustment is small or moves M7 away from the market. |

## Scoring

The information advantage of a match is ln(p_market(outcome) / p_M7(outcome)). Put it in groups by disagreement size and by each possible predictor. For quantities at club level, calculate the uncertainty by resampling club-seasons or match rounds. Do not resample independent matches.

## Conditions to stop or change the work

- Club effects from earlier seasons can fail to predict later residuals, with a correlation below 0.2 and sign agreement below 60%. If they fail, stop the use of club identity as a mechanism.
- The certainty-equivalent forecast can remove less than one quarter of the slope gap. If it does, do not recommend an uncertainty experiment on match evidence alone.
- Recommend a model experiment only if it names a missing mechanism. It must also have a score on outcomes without the market.
