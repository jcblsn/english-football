# Product contract

This page states what the product forecasts and what each forecast must contain. [Operations](operations.md) states how the product runs and what it publishes.

## Scope

The product forecasts the four divisions of the English league:

- Premier League
- Championship
- League One
- League Two

M10 makes every published forecast in every division. M2 is the benchmark. The [methodology](methodology.md) describes both models. M10 is frozen. A change to the structural model needs the evidence that [validation](validation.md) describes.

## Contents of each forecast archive

Each M10 archive contains:

- structural H/D/A probabilities and an exact-score matrix for each remaining fixture;
- a market-assisted H/D/A probability when a captured pre-closing quote exists;
- the full final-points and final-position distribution of every club;
- expected and median points and rank, with central 50%, 80% and 90% intervals;
- for the Premier League: title, top-four, top-five and relegation probabilities;
- for the Championship, League One and League Two: title, automatic promotion, playoff qualification, playoff promotion, promotion and relegation probabilities, under the places of that division and season;
- conditional season events of every club, for each match in the impact window of a week;
- a list of postponed or undated fixtures and the day the simulation used;
- a list of the matches that started without a full-time result, with the assumption that applies to them;
- the data cutoff, the generation time, the input provenance and the seed.

## Hindcasts

A hindcast is a separate, retrospective product. It gives the season estimates of each club at each Wednesday of a completed season, 2021/22–2025/26, in the four divisions. The frozen public model and the structural simulation make it after the season. A hindcast is not a forecast that existed at its origin, and the prospective record does not include it. [Operations](operations.md#hindcasts) gives its rules and layout.

## Checks on each archive

`uv run epl-forecast verify` checks an archive against this contract. The product publishes nothing unless every check passes. The checks are:

1. Every match probability set is a distribution.
2. Every score matrix, plus its omitted tail, sums to one and gives the published H/D/A probabilities.
3. The model cutoff is the London day of the data observation. Training stops before that day.
4. Every club has a points distribution and a rank distribution that sum to one.
5. The total probability of each season event equals the places the rules award.
6. The simulation used the ranking rules of that division and season.
7. The simulation applied the sanctions in force at the cutoff.
8. The playoff bracket is the reviewed edition for the season and uses the latent states of each path. Promotion equals automatic promotion plus playoff promotion.
9. The conditional impacts divide the paths completely, measure every club and return the published season events. The impact window opens on the London day of the observation and closes at the horizon.
10. The simulated match frequencies agree with the published match model within the Monte Carlo tolerance.
11. Each postponed or undated fixture is listed and placed on the cutoff day. Each match that started without a result is listed, is placed on the cutoff day, and gets no match forecast.
12. The provenance records the data manifest, the model specification, the seed and the source hashes.

## Why M10

M7 had the best retained match score and the best season distributions against M2 in the evaluation that [validation](validation.md) summarizes. M10 replaced the Quality dynamics of M7 after a chronological comparison of match scores and season panels in all four divisions. Neither model wins every metric at every origin. The same page records where the earlier model or M2 is close or better.

## Out of scope

- In-play forecasts. A match that is in play is simulated as a match that is not played. The product does not use the current score, and it says so in each forecast that contains such a match.
- Lineup, injury and transfer effects.
- Betting advice or automation.
- Forecasts for cups or European competitions.
