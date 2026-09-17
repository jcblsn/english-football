# Methodology

M10 makes every published forecast. M2 is the benchmark. This page describes both models and the information rules that apply to them. The code is in `src/epl_forecast/models/`.

## M10 team state

Each club has two latent strengths on the log scale:

- Quality (Q) is relative strength. Q is (attack + defense) / 2. Q is the sum of two parts: a persistent club level and a form deviation from that level.
- Tilt (T) is openness. T is (attack − defense) / 2. A positive Tilt raises the expected goals of both teams.

The state also holds a league scoring level (L) and a home advantage (H). The expected goals of each team in a match are:

```text
home rate = exp(L + H + Q_home − Q_away + T_home + T_away)
away rate = exp(L     − Q_home + Q_away + T_home + T_away)
```

Tilt is centered: the Tilts of all registered clubs sum to zero. The filter stores the Tilts as orthonormal contrasts, so L and the Tilts are identifiable. A separate "scoring memory" coordinate keeps the old mean-reverting behaviour of the common Tilt level. That coordinate has no direct effect on any match observation. It changes only how L evolves over time.

## Dynamics

The state evolves in calendar time, not in match rounds.

| Component | Annual retention | Annual innovation SD |
| --- | ---: | ---: |
| Quality level | 1.00 | 0.08 |
| Quality form | 0.30 | 0.07 |
| Tilt | 0.50 | 0.07 |

The Quality level is a random walk. It does not return to the league mean, so a club that is strong or weak for many seasons keeps that level until results change it. The form returns to the level: after one year, 30% of a form deviation remains. Thus a run of results can change the forecast quickly without a permanent change of the level. The filter learns the level and the form together from the same observations. The model before M10, M7, had one Quality process that returned to the league mean with annual retention 0.85. That return made the persistent differences between clubs too small.

The match likelihood sees only the difference of the Quality of two clubs, so it does not observe the common Quality of all clubs. The entry priors fix this reference: each entry prior is relative to the mean of its division, and each season of entrants ties the division to that reference again. Thus the uncertainty of the common Quality does not increase without a limit, although the level is a random walk. A forecast between two clubs with filtered states does not depend on the common Quality. A forecast for an entrant depends on it a little, because the entrant prior is relative to the division.

The league level and the home advantage follow slow random walks. A long gap between matches adds uncertainty.

## Observations: goals and xG

For each team in a match, M10 assumes a latent number of chances N:

```text
N | rate, p  ~ Poisson(rate / p)
xG | N, p    ~ Gamma(shape = N, scale = p)    (xG = 0 when N = 0)
goals | N, p ~ Binomial(N, p)
```

The goals then have a Poisson(rate) marginal distribution. Thus score forecasts stay coherent with the observation model. The xG is the provider's team xG for the match. It is not a count and it is not a sum of shot values.

The chance probability p controls how noisy xG is. M10 uses three values of p (0.1, 0.2 and 0.35) with equal prior weight. Each value gives one filter. The chronological evidence of each filter updates its weight. Forecasts use the weighted mixture of the three filters.

M10 uses API-Football team xG from the first match with API-Football xG in each division: 18 January 2023 in the Premier League, 4 August 2023 in the Championship and 15 August 2026 in League One and League Two. Before that date, the Premier League uses Understat team xG. The two providers never measure the same match in M10. A match without xG updates the state on goals only. Each division's filter updates only on the matches of that division.

## Inference

M10 is a daily Gaussian filter. All matches on one date update the state together, after the forecasts for that date. Each update uses a Laplace approximation at the posterior mode and keeps the full state covariance. This is approximate Bayesian filtering. It does not sample complete latent histories.

## Clubs that enter a division

A club that did not play the division last season gets an entry prior. One rule applies at every division boundary. The prior of an entering club has three parts:

1. An intercept for its transition, for example "promoted from League One".
2. A coefficient on its strength in the division it came from last season.
3. A coefficient on its own older seasons in the target division. The weight of an old season decays with its age. The model averages over several decay rates.

The coefficients come from earlier clubs that made the same transition. Only transitions whose target season finished before the entry date are used. The prior carries residual, coefficient and source-measurement uncertainty.

The training label of the prior is the strength of an entering club over its whole entry season, relative to the mean of the clubs of that season, with the measurement noise of the label removed. The prior therefore describes the persistent level of the entrant. It does not describe the variation of Quality in the season. For this reason the prior gives the Quality level, and the form of an entering club starts at zero with the stationary uncertainty of the form process. The total Quality uncertainty of an entrant is the prior uncertainty plus the form uncertainty. A pre-merge check that gave the whole prior uncertainty to the sum of level and form made entrant match forecasts and season distributions worse.

Each division reads only the divisions that the calibration found useful:

| Forecast division | Divisions its entry priors read |
| --- | --- |
| Premier League | Premier League, Championship |
| Championship | Premier League, Championship |
| League One | Championship, League One, League Two |
| League Two | League One, League Two |

`configs/product.toml` holds this table.

## Match forecasts

A match forecast integrates the uncertainty of the two teams' log rates with Gauss–Hermite quadrature (9 × 9 nodes). Given the rates, the two scores are independent Poisson counts. The H/D/A probabilities use the full score support. The published exact-score grid states the probability mass that falls outside it.

## Matchday-squad continuity

From model version v0.2, a temporary personnel adjustment moves the expected goals of a near fixture in the Premier League or the Championship. The adjustment changes the log rates of that fixture only. It does not change the persistent team state, and the filter does not learn from it. The code is in `src/epl_forecast/personnel.py`.

The recent weight w_j of player j is the number of minutes, capped at 90, that the player played in the eight previous club matches that kicked off before the forecast cutoff. Each of these matches must have at least 700 recorded minutes. The matchday-squad discontinuity of a club is:

```text
D = 1 − Σ_j w_j p_j / Σ_j w_j
```

p_j is the probability that player j is in the matchday squad of the fixture:

- An official team sheet captured before the cutoff gives 1 or 0. The sheet must have 11 starters and at least 7 substitutes.
- Otherwise, a player who has left the club gives 0. A dated transfer from the club, or a matchday squad of another club after the last matchday squad for this club, shows a departure.
- Otherwise, a club member gives availability × q(m, n). m is the number of the eight matchday squads that included the player, and n shows whether the last one did. q comes from Premier League and Championship matches in 2021/22–2025/26. For example, q(8, yes) is 0.959 and q(1, no) is 0.297.

Availability is 0 for an API-Football unavailable status or an FPL status of i, s, n or u. It is 0.3 for a doubtful status or FPL d, and 1 otherwise. API-Football statuses must name the same club and fixture, and FPL statuses must name the same club. For a Premier League player, a usable FPL status takes priority when API-Football disagrees. The evidence record keeps both source values. This policy is explicit so that it is easy to review if later source problems occur. Membership comes from dated transfers and matchday squads first. Without them, the latest squad snapshot and the FPL club decide when they agree. Two strong observations of the same day that disagree leave membership unknown, because the evidence does not order them.

Availability 1 is not a statement that a player is fit. A provider lists only the players it reports, and API-Football publishes the list of a fixture a short time before kickoff, so absence from a response is not proof of availability. The record says which case holds: the fixture appears in an injury snapshot and the player is not named in it, or no snapshot covers the fixture. The residual risk sits in q(m, n), which was fitted without the players that the injury lists named.

A player with unknown membership or an unknown status is unresolved and is left out. A club with more than 25% unresolved recent weight gets no adjustment.

The shift is:

```text
Δ = κ (D_away − D_home), κ = 0.4316
home log rate + Δ
away log rate − Δ
```

κ was fitted once on the realized matchday squads of 8,073 Premier League and Championship matches in 2017/18–2025/26. It is not fitted again on later results.

Only a fixture that kicks off in the six days after the cutoff gets the shift. Six days is the longest checkpoint of the prospective evaluation, so the prospective record can measure the horizon that the product deploys. It is a frozen deployment choice under monitoring, not an optimized one: no search selected it, and no evidence says that six days scores better than five or seven. It stays fixed while prospective evidence collects.

Each production run calculates the shift again, so the forecast changes when squads, injury lists, FPL statuses and team sheets change. The published match forecast gives the discontinuity of each club and the home log-rate shift.

## Season paths

Each simulated season path does these steps:

1. Pick one of the three filters by its weight.
2. Draw the current joint state of all clubs from that filter's posterior.
3. Draw entry states for clubs with no match yet this season.
4. Move the state forward to each fixture date, with random innovations.
5. Draw each score from that path's state. A fixture in the next six days also gets its matchday-squad continuity shift.

Simulated scores do not update the state. The simulator then builds the table and applies the rules in [season simulation](simulation.md).

## Market-assisted probabilities

The market-assisted H/D/A probability pools M10 with the de-vigged average pre-closing odds. The pool is a logarithmic pool with one weight. The weight was fitted chronologically on 2023/24–2025/26 and is 1.0. Thus the market-assisted probability is currently the de-vigged market probability. It is published only when a captured quote exists. It never enters the season simulation or the exact-score grid. `configs/market_pool.json` holds the fit.

## M2 benchmark

M2 is a ridge-regularized Poisson model with one attack and one defense value per club, a league level and a home advantage. It uses 1,095 days of results from the forecast division, with a 365-day half-life and a ridge penalty of 5. A club without history gets league-average strength. M2 has no state uncertainty, so its season paths show only match randomness.

## Information rules

- `--cutoff` limits the inputs to evidence retrieved by that time.
- Model fitting excludes results from the London calendar day of the cutoff.
- The current table fixes every captured full-time score, including that day.
- Historical evaluation assumes that a result and its xG are available on the day after the match.
- Personnel evidence uses only rows retrieved by the cutoff. A hindcast dates a matchday squad from the London day after its match and a transfer from its date. It uses no injury lists, squad captures, FPL statuses or team sheets, because the data does not show when they were first known.
- Squad, injury and FPL evidence is selected by source snapshot, not by taking the latest rows of a table. Each scope has one latest snapshot at the cutoff, and only the rows of that retrieval count. A response that held no rows therefore clears its scope, and a response retrieved later for another competition, season or club cannot supersede this one. See [data and provenance](data.md#production-contracts-of-the-player-tables).
- For a completed reference match, one latest usable capture of each club gives the participants and the minutes. A correction replaces what it corrects. Before kickoff every capture is kept, because the team-sheet rule wants the latest one that names a whole matchday squad.
