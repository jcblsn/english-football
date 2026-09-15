# Limitations

Read the forecasts with these limits in mind.

## Evidence

- The historical evaluation is retrospective. It assumes that a result and its xG are available on the day after the match. Historical odds have no quote times.
- Each season panel has only nine to eleven seasons. Its intervals are wide. See [validation](validation.md).
- Hindcasts are retrospective. The model specification was developed with the same history, so hindcasts can look better than live forecasts. They use the fixture dates that each season finally used, and they assume that results and xG were available on the day after each match.
- The prospective record starts fresh before launch. It will have few settled matches at first.
- The only comparison is with M2 and with the betting market. There is no comparison with public forecast models yet.

## Inputs

- Only the Premier League has xG. The other three divisions use goals only.
- M7 does not use lineups, injuries, suspensions or transfers.
- The production workflow wakes each hour. Fixture lists are eligible each hour, and match details are eligible every 15 minutes around kickoff. An hourly wake can still miss very late team news.
- The model does not forecast future sanctions or appeals. A forecast applies only the sanctions known at its cutoff.

## Model

- The filter is an approximation. It uses a Laplace step each day and a finite set of three noise values.
- Dynamics parameters are fixed. They are not estimated from the data.
- Entry priors come from few clubs at some boundaries, for example clubs promoted from a curtailed season. Their intervals can be too wide or too narrow.
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
