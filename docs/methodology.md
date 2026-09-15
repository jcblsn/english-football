# Methodology

M7 makes every published forecast. M2 is the benchmark. This page describes both models and the information rules that apply to them. The code is in `src/epl_forecast/models/`.

## M7 team state

Each club has two latent strengths on the log scale:

- Quality (Q) is relative strength. Q is (attack + defense) / 2.
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
| Quality | 0.85 | 0.09 |
| Tilt | 0.50 | 0.07 |

The league level and the home advantage follow slow random walks. A long gap between matches adds uncertainty. Previous seasons persist, with decay.

## Observations: goals and xG

For each team in a match, M7 assumes a latent number of chances N:

```text
N | rate, p  ~ Poisson(rate / p)
xG | N, p    ~ Gamma(shape = N, scale = p)    (xG = 0 when N = 0)
goals | N, p ~ Binomial(N, p)
```

The goals then have a Poisson(rate) marginal distribution. Thus score forecasts stay coherent with the observation model. The xG is the provider's team xG for the match. It is not a count and it is not a sum of shot values.

The chance probability p controls how noisy xG is. M7 uses three values of p (0.1, 0.2 and 0.35) with equal prior weight. Each value gives one filter. The chronological evidence of each filter updates its weight. Forecasts use the weighted mixture of the three filters.

M7 uses API-Football team xG from the first match with API-Football xG in each division: 18 January 2023 in the Premier League, 4 August 2023 in the Championship and 15 August 2026 in League One and League Two. Before that date, the Premier League uses Understat team xG. The two providers never measure the same match in M7. A match without xG updates the state on goals only. Each division's filter updates only on the matches of that division.

## Inference

M7 is a daily Gaussian filter. All matches on one date update the state together, after the forecasts for that date. Each update uses a Laplace approximation at the posterior mode and keeps the full state covariance. This is approximate Bayesian filtering. It does not sample complete latent histories.

## Clubs that enter a division

A club that did not play the division last season gets an entry prior. One rule applies at every division boundary. The prior of an entering club has three parts:

1. An intercept for its transition, for example "promoted from League One".
2. A coefficient on its strength in the division it came from last season.
3. A coefficient on its own older seasons in the target division. The weight of an old season decays with its age. The model averages over several decay rates.

The coefficients come from earlier clubs that made the same transition. Only transitions whose target season finished before the entry date are used. The prior carries residual, coefficient and source-measurement uncertainty.

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

## Season paths

Each simulated season path does these steps:

1. Pick one of the three filters by its weight.
2. Draw the current joint state of all clubs from that filter's posterior.
3. Draw entry states for clubs with no match yet this season.
4. Move the state forward to each fixture date, with random innovations.
5. Draw each score from that path's state.

Simulated scores do not update the state. The simulator then builds the table and applies the rules in [season simulation](simulation.md).

## Market-assisted probabilities

The market-assisted H/D/A probability pools M7 with the de-vigged average pre-closing odds. The pool is a logarithmic pool with one weight. The weight was fitted chronologically on 2023/24–2025/26 and is 1.0. Thus the market-assisted probability is currently the de-vigged market probability. It is published only when a captured quote exists. It never enters the season simulation or the exact-score grid. `configs/market_pool.json` holds the fit.

## M2 benchmark

M2 is a ridge-regularized Poisson model with one attack and one defense value per club, a league level and a home advantage. It uses 1,095 days of results from the forecast division, with a 365-day half-life and a ridge penalty of 5. A club without history gets league-average strength. M2 has no state uncertainty, so its season paths show only match randomness.

## Information rules

- `--cutoff` limits the inputs to evidence retrieved by that time.
- Model fitting excludes results from the London calendar day of the cutoff.
- The current table fixes every captured full-time score, including that day.
- Historical evaluation assumes that a result and its xG are available on the day after the match.
