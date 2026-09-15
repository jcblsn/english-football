# Season simulation

The simulator plays every remaining regular-season fixture on each season path. It then builds the final table and applies the rules of the division and season. The code is in `src/epl_forecast/simulation.py` and `src/epl_forecast/postseason.py`. The rules are in `src/epl_forecast/data/rules.py`.

## Division rules

A win gives 3 points and a draw gives 1 point.

| Division | Clubs | Automatic promotion | Playoff places | Relegated |
| --- | ---: | ---: | --- | ---: |
| Premier League | 20 | — | — | 3 |
| Championship | 24 | 2 | 3rd–8th (3rd–6th before 2026/27) | 3 |
| League One | 24 | 2 | 3rd–6th | 4 |
| League Two | 24 | 3 | 4th–7th | 2 |

Tie rules:

- Premier League: points, goal difference, then goals scored. From 2019/20, head-to-head points and away goals decide a tie that affects the title or relegation.
- EFL divisions: points, goal difference, goals scored, then head-to-head results. The archive has no disciplinary records. A tie that remains after these steps splits its rank probability equally.
- A tie that does not affect an event shares its places for reporting. A deciding tie that remains gets equal chances.

## Season events

| Division | Events |
| --- | --- |
| Premier League | title, top four, top five, relegation |
| EFL divisions | title, automatic promotion, playoff qualification, playoff promotion, promotion, relegation |

Top four and top five are table positions. They are not European qualification. The verifier checks that the total probability of each event equals the number of places the rules award.

## Playoffs

The simulator plays the playoff bracket after every regular-season path. Each tie uses the latent team states of that path. Thus a club plays at the strength that its own path gave it.

- Championship 2026/27: the clubs in 5th to 8th play single-match quarter-finals. The winners meet 3rd and 4th in two-legged semi-finals. A neutral final follows.
- League One and League Two: two-legged semi-finals put the first playoff place against the fourth, and the second against the third. A neutral final follows.

Three approximations apply:

1. A tie that is level after normal time goes to each club with equal chance.
2. The neutral final uses an equal mixture of the two home designations.
3. Playoff dates are synthetic offsets from the last regular-season match.

Each forecast records these approximations in its `playoff_model` block.

## Sanctions

A forecast applies only the sanctions known at its cutoff. A sanction is known from its reviewed announcement date. If there is no reviewed date, it is known from the first captured league table that shows it. The current table and the projection both carry each known sanction.

For historical scoring, the realized final table includes every sanction in force at the end of the season. The simulator does not forecast future sanctions.

## Fixtures without a usable date

- A postponed or undated fixture is simulated on the cutoff day. When the provider gives a new date, only the date of its state evolution changes. The archive and the public forecast list each such fixture with the day that the simulation used.
- A match that started without a full-time result is simulated on the cutoff day, as a match that is not played. The forecast does not use the current score. It gives no match probabilities for that match, and it lists the match with the assumption that applies to it. The projection of the two clubs is a pre-match projection that is one match behind the live table.

## Conditional impacts

The impact window is the slate of a week. It opens at the start of the current day in Europe/London and closes seven days after the observation. For each match in the window that is not played, the simulator divides its own paths by the result of that match. It then reads the season events of every club in each group. A club that does not play in the match is included, because a result also moves the clubs around it. The simulator does not run a new simulation. The movement of an event is

```text
sqrt( sum over results r of P(r) × (P(event | r) − P(event))² )
```

These numbers are conditional forecasts. They are not causal effects. The verifier checks that the groups cover all paths, that the weighted conditionals return the published event probability, and that every club is measured against every match. A result with fewer than 100 paths is marked as a thin sample.

A match of the current day that already has a result is not measured again. After the result is known, the current paths cannot give an honest statement about the other results. The published forecast carries the record of the last forecast that was made before the kickoff. The record names that forecast and holds its baseline and the result of the match. If no forecast from before the kickoff measures every club, the match shows no numbers and says why.

## European places

`--europe-scenario` gives Premier League European qualification under an explicit cup scenario. See `configs/europe_scenario.example.json`. The product does not publish this output.
