# English league forecasts

Probabilistic forecasts for the four divisions of English league football: the Premier League, the Championship, League One and League Two. The product forecasts every remaining match and the final table of each division. An hourly production job checks for new effective inputs and publishes only when they change.

## What it forecasts

For each remaining match:

- home, draw and away probabilities;
- an exact-score distribution;
- a market-assisted probability when a betting-market quote exists.

For each club:

- the full distribution of final points and final position;
- expected points and rank, with 50%, 80% and 90% intervals;
- title, top-four, top-five and relegation probabilities (Premier League);
- title, automatic promotion, playoff, promotion and relegation probabilities (Championship, League One and League Two), with the playoff bracket simulated.

The forecasts also show how much each fixture in the next seven days can move each club's season.

## Model

One model, M7, makes every published forecast. M7 gives each club a latent strength and a latent openness. These change over time. Goals and expected goals (xG) update them each day. Clubs that change division start from priors learned from earlier clubs that made the same move. Each simulated season draws the uncertain team strengths and lets them change until the last match. A simpler Poisson model, M2, is the benchmark.

See the [methodology](docs/methodology.md) and the [season simulation rules](docs/simulation.md).

## Public forecasts

Forecast documents are immutable objects in the private `page324-publish` R2 bucket. The forecast index identifies the latest successful document for each division. A separate `record.json` scores settled forecasts. The Pages workflow materializes this sanitized surface into its deployment artifact. Generated forecasts are not committed to Git. Weekly hindcasts of the completed seasons 2021/22–2025/26 are a separate, retrospective product under `hindcasts/`. They never enter the forecast index or the record. See [operations](docs/operations.md#hindcasts).

To view the forecasts on your computer:

```sh
uv run python -m http.server -d site 8000
```

Then open <http://localhost:8000>. Run `uv run epl-forecast materialize` first to load the current publication data from R2. The GitHub Pages workflow does the same step before deployment.

## Run it

You need [uv](https://docs.astral.sh/uv/), an API-Football key and credentials for the two private R2 buckets. Provider data is not in this repository.

```sh
uv sync --locked
export API_FOOTBALL_KEY=...                # or put it in an ignored .env file
uv run epl-forecast operate
```

`operate` collects new data, writes canonical data and private runs to R2, verifies due forecasts, and publishes the sanitized documents to R2. See [operations](docs/operations.md).

## Validation

- Every forecast archive passes the checks in the [product contract](docs/mvp.md) before publication. For example, event probabilities must sum to the places that the rules award.
- Historical season panels compare M7 with M2 in every division: rank, points and event scores at five points in each season.
- A match scoreboard compares M7 with M2 and with the betting market.
- The prospective record scores each published forecast after the match.

The [validation summary](docs/validation.md) gives the results and the commands to reproduce them.

## Limitations

- xG comes from API-Football. It starts in 2023 in the Premier League and the Championship and in August 2026 in League One and League Two. A match without xG updates the model on goals only.
- The model does not use lineups, injuries or transfers.
- The historical evaluation is retrospective, and it covers only nine to eleven seasons in each division.
- Some playoff and scheduling details are explicit approximations.

See all [limitations](docs/limitations.md).

## Documentation

| Document | Content |
| --- | --- |
| [Product contract](docs/mvp.md) | What each forecast contains and the checks it must pass |
| [Methodology](docs/methodology.md) | The M7 model and the M2 benchmark |
| [Season simulation](docs/simulation.md) | Division rules, playoffs, sanctions and fixture dates |
| [Data and provenance](docs/data.md) | Providers, storage, identity and data commands |
| [Operations](docs/operations.md) | Running, scheduling, publishing and the forecast record |
| [Validation](docs/validation.md) | Evidence for M7 and how to reproduce it |
| [Limitations](docs/limitations.md) | What the forecasts do not cover |
| [Research history](docs/research.md) | Where the experiments and older models are kept |

## Development

```sh
scripts/verify.sh
```

This formats, lints and tests the code. GitHub Actions runs the same checks and the publication boundary check on every push and pull request.

Provider data is used under each provider's terms. It is not redistributed.
