# M10 Quality dynamics: plan

Status: recorded on 17 September 2026 before any candidate result. Branch: `research-m10-quality-dynamics`. Main base: `c7d94c7`.

## Question

How must the persistent Quality of a club change with time? The `research-market-disagreement` study (memo of 17 September 2026) gives these hypotheses. That study used the same Premier League seasons 2016/17–2025/26 that this plan scores, so those seasons are not a clean holdout.

- H1. The M7 Quality process returns to the league mean too quickly. The persistent differences between clubs are larger and last longer than the process permits. Thus the filter compresses clubs that are strong or weak for many seasons.
- H2. Quality has two parts with different time scales: a persistent club level and a short deviation that returns to that level. A single AR(1) process cannot describe both. A slow process follows short deviations too slowly, and a fast process forgets the level too quickly.

## Mechanism

M7 Quality is an AR(1) process in calendar time: annual retention ρ = 0.85 and innovation SD σ = 0.09 per √year. The stationary SD is 0.171 and the half-life is 4.3 years. The filter shrinks each club toward zero with this rate, also during the close season. If the true persistent level of a club is far from zero, each forecast gives the club a Quality that is too near zero, and the model learns again from results the part that it removed.

The return to zero also has a second function. The likelihood sees only differences of Quality. The return to zero keeps the mean Quality of the division near zero, which is the scale of the entry priors. A candidate without this return must keep the division mean consistent with the entry priors. The analysis measures the drift of the division mean Quality for each candidate.

## Candidates

The candidates are fixed before results. Every candidate keeps the M7 observation model, the Tilt dynamics, the entry priors, the league block and the mixture over the chance probability.

| ID | Structure | Rationale |
| --- | --- | --- |
| C0 | M7: AR(1), ρ = 0.85, σ = 0.09 | Control |
| C1 | AR(1) on the grid ρ ∈ {0.85, 0.95, 1.00} × σ ∈ {0.06, 0.09, 0.12} | H1. The persistence and the innovation scale are selected together, because a larger σ also decreases the effective shrinkage. |
| C1-FC | For each test season, the C1 grid point with the best score on earlier seasons | A chronological selection of one point |
| C1-BMA | A mixture over the C1 grid, weighted by the chronological evidence of each filter | Uncertainty over the dynamics. This is the M7 machinery for a mixture of specifications. |
| C2 | Quality = persistent club level L + deviation F. L is a slow process and F is a fast AR(1) toward L. | H2. The owner decided on 17 September 2026 to build C2 for comparison in all cases. |

The C2 grid is L a random walk with σ_L ∈ {0.04, 0.06}, and F an AR(1) with ρ_F = 0.3 and σ_F ∈ {0.10, 0.15}. The half-life of F is 7 months, so most of a deviation ends within one season and the close season. An entering club gets its entry prior on L and the stationary distribution on F. C2-FC and C2-BMA use the same selection rules as C1.

C2 is a larger change: each club needs a third state slot. One test that does not use the market or the match scores of the candidates gives independent evidence for or against H2:

- Martingale test. Under a correct random-walk filter, the filtered Quality is a martingale: a change in the last k matches does not predict the change in the next k matches. A negative slope shows a short deviation that returns (H2). A positive slope shows a filter that is too slow. Under an AR(1) filter, the test compares the mean change with the change that the model expects.

## Evaluation

- Rolling daily forecasts in the four divisions, from the first match day with 700 earlier matches in the division until 16 September 2026. The fit, training data and entry priors are those of the product.
- Test seasons: 2015/16–2025/26 in each division. League One and League Two include 2019/20 in the match scores, but not in the season panels. The partial 2026/27 season is reported separately.
- Forward-chaining selection: a season S uses only scores of seasons before S, from 2012/13. Selection uses the pooled score NLL of all four divisions. The same dynamics apply to every division, because a model that has different dynamics in each division has no support from theory.
- Primary match metrics: H/D/A log loss and score NLL. Also Brier score and classwise calibration.
- Slices: season, division, entrants and continuing clubs, the first ten matches of a club in the season and later matches, and clubs by quintile of preseason Quality.
- Intervals: paired differences with blocks of 28 days in each season, and the effect of each season.
- Season panels: `scripts/evaluate_seasons.py` with M7 and the selected candidate on the same seasons, origins, seed and 10,000 paths. Rank RPS, points CRPS, event Brier scores, and the coverage and width of the intervals, in each division.
- Market: only after the outcome results. The market slope and the club effects of the disagreement study, for the Premier League.

## Stop and redirect

- If no C1 grid point other than C0 improves the pooled score NLL in forward-chaining selection, H1 is rejected for this model, and the work stops without an M10 change.
- If a candidate improves the Premier League but makes the pooled score of the three EFL divisions worse, it is not a model for all divisions. The memo reports this and does not recommend a merge.
- If a candidate improves match scores but makes the 90% points coverage worse by more than 3 points at two or more origins in a division, the season uncertainty must be examined before a merge.
- C2 replaces C1 only if it improves the forward-chaining score NLL of the best C1 in the pooled test seasons, and its season effects are not worse in most seasons.

## Amendment of 17 September 2026

The first C2 grid selected σ_L = 0.06 and σ_F = 0.10 in each forward-chaining season from 2015/16. That point is at the edge of the grid. Before any result of new points, the C2 grid adds one step outward: (σ_L, σ_F) ∈ {(0.06, 0.07), (0.08, 0.07), (0.08, 0.10)}. C2-FC selects from all seven points. ρ_F stays at 0.3. The first grid, its results and its selections stay in the record.
