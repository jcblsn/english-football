# M10 pre-merge checks: plan

Status: recorded on 17 September 2026, before any result of the candidates below. Branch: `research-m10-quality-dynamics`. Production branch: `m10-quality-dynamics`. The steering memo of 17 September 2026 asks for bounded checks before the merge, not for a new model search.

The first diagnostic of the reference frame (check 1) ran before this plan was written. Its result is in the memo. No candidate of checks 2 and 4 had a result when this plan was written.

## Check 1. Reference frame of the Quality level

The match likelihood sees only differences of Quality. At a preseason and a midseason cutoff in each season and division, the diagnostic fits one observation-noise member (chance probability 0.2) of M10 and of M7 and measures:

- the posterior mean and SD of the mean Quality of the clubs that continue into the season;
- the part of the entrant-minus-incumbent Quality variance that comes from that common direction;
- the forecasts of the first ten matches of each entrant against a continuing club, from the preseason state, as the filter makes them and with the entrant referenced to the mean Quality of all clubs of the season, which is the reference of the entry-prior labels.

A fix is necessary only if the common-direction variance grows without a limit, or is a material part of the entrant predictive variance, or if the referenced forecasts are better in most divisions.

## Check 2. Entrant initialization

The entry-prior label is the division-relative strength of a club in its entry season. M7 gave that prior to the whole Quality of the entrant. M10 gives it to the level and adds the stationary form variance (0.07² / (1 − 0.3²) = 0.0054), so the total Quality variance of an entrant is larger than the entry prior.

Candidate E1 keeps the total: the entrant form keeps its stationary distribution, and the level variance is the entry-prior Quality variance minus the form variance. If the entry-prior Quality variance is less than twice the form variance, the form gets half of it. The Quality–Tilt covariance is decreased when necessary to keep the covariance positive definite.

Evaluation: rolling match forecasts in all four divisions with the M10 method, the slices of the M10 memo (in particular the first five and first ten matches of a club and entrant matches), and the season panels at all origins with the M10 panel settings. E1 replaces the current treatment only if the entrant-match score NLL and log loss are not worse in the pooled test and the preseason points CRPS and rank RPS are not worse in most divisions. Otherwise the current treatment stays and the memo documents its meaning.

## Check 3. Personnel adjustment on M10

The history-only hindcast of the matchday-squad adjustment (`research/evidence/personnel-measurement/68cba95/pm-hindcast-report/chronological.csv` in `page324-data`) gives, for each Premier League and Championship match in 2020/21–2025/26, the estimated D_away − D_home and the shift with the earlier-season κ. The check applies the same shifts to rolling M10 forecasts and to rolling M7 forecasts from the same code and data. It also applies the frozen κ = 0.4316. No coefficient is fitted. The metrics are H/D/A log loss, Brier score and score NLL, with the slices of the validation document and 12 competition-season clusters.

The adjustment stays if the pooled hindcast score NLL difference against M10 is below zero and its gain is not much smaller than against M7 (at least half). If the gain against M10 is zero or positive, the adjustment is removed or deferred.

## Check 4. Close-season level transition

Hypothesis: the level of a club changes more between seasons than within a season. At the first match of a continuing club in a new season, its level gets one more independent innovation with SD σ_c. An entrant does not get it, because its entry prior already describes the new season. Form, Tilt and the entry priors do not change. The transition applies in all four divisions and in the season simulation.

Two candidates, fixed before results:

- S1: σ_c = 0.08 in addition to the calendar-time level walk (σ_L = 0.08).
- S2: the same annual level variance, one half at the boundary: σ_c = σ_L = 0.08 / √2 = 0.0566.

Evaluation: the same rolling match scores and season panels as M10. A candidate replaces M10 only if all of these are true:

1. The pooled test log loss and score NLL are lower than M10.
2. The Premier League log loss is not worse than M10 by more than 0.0005.
3. The mean log loss of EFL club matches 1–5 decreases by at least one third of the M10-minus-M7 difference in those matches.
4. In the season panels, no division has a points CRPS or rank RPS difference against M10 with an interval above zero at two or more origins.

If both pass, the candidate with the lower pooled score NLL is chosen. If neither passes, M10 stays and the search stops. No further σ_c is tested.
