# Limitations

Read the forecasts with these limits in mind.

## Evidence

- The historical evaluation is retrospective. It assumes that a result and its xG are available on the day after the match. Historical odds have no quote times.
- Each season panel has only nine to eleven seasons. Its intervals are wide. See [validation](validation.md).
- Hindcasts are retrospective. The model specification was developed with the same history, so hindcasts can look better than live forecasts. They use the fixture dates that each season finally used, and they assume that results and xG were available on the day after each match.
- The prospective record starts fresh before launch. It will have few settled matches at first.
- The matchday-squad continuity adjustment of v0.2 was released on retrospective evidence. Its representation and coefficient were chosen with the same seasons, and no prospective fixture was scored before the release. See [validation](validation.md#matchday-squad-continuity).
- The only comparison is with M2 and with the betting market. There is no comparison with public forecast models yet.

## Inputs

- API-Football xG starts in January 2023 in the Premier League, August 2023 in the Championship and August 2026 in League One and League Two. The League One and League Two xG has no historical evaluation. A match without xG updates the state on goals only.
- The persistent M10 state does not use lineups, injuries, suspensions or transfers. Only the temporary continuity adjustment uses them, and only for Premier League and Championship fixtures in the next six days. League One and League Two have no adjustment.
- A club without eight previous matches with complete lineup minutes, for example a club promoted from League One, has no adjustment until it has them.
- An official team sheet enters the adjustment only when a production run captures it before the forecast cutoff.
- API-Football publishes the injury list of a fixture only a short time before the match. An adjustment several days before kickoff therefore uses membership and FPL status, and in the Championship membership only. [Validation](validation.md#matchday-squad-continuity) records what the injury lists covered at the release.
- A player that no provider reports is treated as not listed, not as proven fit. Absence from an injury response is not a statement about a player. The selection rate q(m, n) carries the residual risk, because it was fitted without the players the injury lists named.
- The production workflow wakes every three hours at minute 15 in `America/New_York`, including 09:15 each Saturday. Fixture lists are eligible each hour, and match details are eligible every 9 minutes in the 75 minutes before kickoff, but they are collected only when a run occurs in that window. GitHub can delay or skip a scheduled run, so a late team-news change can be missed.
- The model does not forecast future sanctions or appeals. A forecast applies only the sanctions known at its cutoff.

## Model

- The filter is an approximation. It uses a Laplace step each day and a finite set of three noise values.
- Dynamics parameters are fixed. They are not estimated from the data.
- Entry priors come from few clubs at some boundaries, for example clubs promoted from a curtailed season. Their intervals can be too wide or too narrow.
- The continuity adjustment has one linear coefficient for both divisions, fixed availability values and one pooled table for q(m, n). It responds only to the difference between the two clubs, so two clubs with the same discontinuity get no shift.
- The six-day horizon is a frozen deployment choice, not an optimized one. It is the longest checkpoint of the prospective evaluation, so the prospective record can measure it. No search chose it, and no evidence says that six days is better than five or seven. It stays fixed while the prospective evidence collects.
- The market-assisted weight is 1.0. Thus the market-assisted probability adds no model information to the market price.

## Season rules

- A tied playoff tie resolves with equal chances for each club. The rules data has no model of extra time or penalties.
- A playoff final uses an equal mixture of the two home designations.
- Playoff dates are synthetic offsets from the last regular-season match.
- A postponed or undated fixture is simulated on the cutoff day until the provider gives a new date. The public forecast lists each such fixture.
- A match in progress, or a result that is overdue, stops the season projection.
- Premier League European places need an explicit cup scenario. The published forecast shows only top-four and top-five positions.

## Operation

- GitHub Actions runs production against the two private R2 buckets.
- The publication bucket stays private. GitHub Pages must materialize its sanitized objects during deployment.
- A checkout of this repository contains no provider data.
