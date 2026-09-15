# Operations

This page states how the product runs, what it publishes and where it keeps old forecasts. The [product contract](mvp.md) states what each forecast contains.

## One command

```sh
uv run epl-forecast operate
```

`operate` does these steps:

1. It loads compact operational state from `page324-data`.
2. It collects each data source when that source is eligible. A retained response that is still inside its refresh interval is not requested, downloaded or normalized again. The run reads a retained body only when collection needs it, for example to find the teams in a fixture list.
3. It uploads only the raw payloads and canonical batches created in this run. It updates the state that makes them visible only after those objects exist. When a run collects nothing new, it does not write the collection state, the manifest catalog or an audit with the same content.
4. It calculates a fingerprint from the effective model inputs, the forecast code and configuration, and the public model version.
5. It runs each division whose last successful fingerprint differs.
6. It verifies each private forecast archive against the product contract.
7. It uploads the private archive to `page324-data`.
8. It writes each verified public document to `page324-publish`, then updates the forecast index and prospective record. A run that publishes nothing writes `record.json` only when a result changes it.

A failed or unverified division does not publish. Other verified divisions in the same run can publish and advance their own latest pointers. The next run retries only the divisions that do not have the current successful fingerprint.

| Option | Effect |
| --- | --- |
| `--force` | Run even if the effective inputs did not change. |
| `--no-collect` | Use the canonical archive as it is. |
| `--simulations 10000` | Set the number of season paths. The publication floor is 1,000. |
| `--runs`, `--data` | Set ephemeral workspace locations. |

## Schedule and refresh rules

`.github/workflows/production.yml` wakes at 17 minutes after each hour and also supports manual dispatch. Source refresh intervals are independent of this wake schedule. GitHub Actions concurrency lets one production run finish before another starts.

Fixture lists are eligible each hour. Match details are eligible every 15 minutes near kickoff and have bounded correction checks after full time. Other sources keep their own intervals.

Each collection run that sends requests to API-Football writes one usage record to `audits/api_football/<UTC timestamp>.json` in `page324-data`. The record has the number of requests and the last daily limit and remaining values from the provider. `audits/collection.json` shows the same values for the most recent run. Use these records to see the real usage over a week.

A new forecast is due only when the effective model inputs for that competition or the statistical model code and configuration change. A schedule change in one division does not cause another division to run. Availability and injury data do not change the fingerprint because M7 does not use them. Publication, site and pipeline code also do not change the statistical fingerprint. A repeated provider response with the same consumed values does not cause publication only because its retrieval time changed.

Routine production does not compact canonical data. Run `uv run python scripts/compact_r2.py` as maintenance after 250 incremental batches collect. The script compacts from an empty workspace, so local files do not enter the R2 history. Use `--force` only when an earlier compaction is useful. Compaction keeps row retrieval times, so historical cutoff reads give the same result before and after maintenance. Later routine runs add only new batches to the compact catalog. Compaction does not delete earlier R2 objects.

GitHub Actions is the normal production writer. The workflow concurrency group prevents two production runs at the same time, but it does not know about local commands. Maintenance and migration writes to R2 must not overlap production. Before such a write, run `gh workflow disable production.yml`, make sure that no production run is in progress, do the write, then run `gh workflow enable production.yml`.

## Model versions

`model_version` in `configs/publication.toml` is the public product version, for example `v0.0`, `v0.1` or `v1.0`. It is separate from the internal model names in `configs/product.toml`, which stay private.

The public version is part of the production fingerprint. When you change it, every division becomes due on the next run, so no current forecast keeps the earlier label. Each forecast document, each pointer and each row in `record.json` keeps the public version that made it. The record summaries can include forecasts from more than one version.

## Single steps

```sh
uv run epl-forecast forecast --competition eng-league-one --output runs/check/l1
uv run epl-forecast verify --archive runs/check/l1 --output runs/check/l1-verification
```

`forecast` writes a private archive: `forecast.json`, `run.json`, CSV tables and an HTML page. `verify` writes `verification.json` and fails if any check fails.

## Publication boundary

`epl_forecast.publication` defines focused key contracts for forecast documents, the current pointer document, competition archive indexes and the performance record. `configs/publication.toml` defines key parts and value patterns that must not appear, such as provider names, file paths and odds.

The code enforces the boundary when it derives a document, before it writes an object, and when `scripts/check_publishable.py` checks the materialized Pages artifact.

Published:

- H/D/A probabilities and the market-assisted probability;
- exact-score grids for each club's next fixture;
- points and position distributions, with their intervals;
- event probabilities and the conditional effect of each match of the week on every club;
- the list of postponed or undated fixtures;
- useful timestamps and the public model version.

Private:

- all provider captures, request records and raw odds;
- private forecast runs and verification reports;
- file hashes, internal model identifiers and full run provenance;
- credentials and internal file paths.

## Publication layout

The pipeline gives each competition forecast its own ID and writes it once to `forecasts/<competition>/<forecast>.json` in `page324-publish`. It updates `forecasts/<competition>/archive.json` after the immutable forecast exists. It updates the compact `forecasts/current.json` document last. The current document has one latest pointer for each division and does not contain history.

Historical forecast documents use unique keys. Competition archive indexes, `forecasts/current.json` and `record.json` are mutable.

## Hindcasts

A hindcast is a retrospective forecast of a completed season. It is a separate product type. The frozen public model makes it after the season, so it is not a forecast that existed at the origin time. Hindcasts never enter `forecasts/current.json`, a competition archive or `record.json`. The publication contracts refuse a hindcast link in a live pointer, and the prospective record refuses a hindcast document. The prelaunch prospective forecasts stay in `forecasts/`. They are not hindcasts.

```sh
uv run epl-forecast hindcast --workers 7
```

The command makes hindcasts for the four divisions in 2021/22–2025/26. Use `--competition` and `--seasons` to make a part of the archive. The `--data` workspace must be empty. The command reads the canonical history from `page324-data`. It does not use the files in the repository `data/` directory.

The rules for each hindcast:

- There is one origin each Monday at 09:00 Europe/London. The first origin is the Monday on or before the first regular-season match. The last origin is the first Monday after the last result. The archive keeps every weekly origin, also when the estimates do not change.
- The model uses the results of matches played before the London day of the origin. It uses the same information rules as the [season panels](validation.md#method): results and xG are available on the day after each match, a points deduction applies from its reviewed announcement date, and the simulation uses the fixture dates that the season finally used.
- The structural model makes the season simulation. A hindcast has no market-assisted probabilities, no match impacts and no score grids.
- Each document lists these assumptions in `assumptions`, and has `"product": "hindcast"` and `"retrospective": true`.

The command writes these objects:

| Bucket | Key | Content |
| --- | --- | --- |
| `page324-data` | `runs/hindcasts/<version>/edition.json` | The model code hashes, the seed, the number of paths and the origin rule of the public model version. It is immutable. |
| `page324-data` | `runs/hindcasts/<version>/<competition>/<season>/<hindcast>.json` | The private simulation output of one origin. It is immutable. |
| `page324-publish` | `hindcasts/<version>/<competition>/<season>/<hindcast>.json` | The sanitized season estimates of each club at one origin. It is immutable. |
| `page324-publish` | `hindcasts/<version>/<competition>/<season>/series.json` | The weekly series of the season. |
| `page324-publish` | `hindcasts/index.json` | One row for each public model version, division and season, with a link to its series. |

The hindcast ID is the origin time in UTC, in the same form as a forecast ID. `origin_at` gives the origin in London time.

The edition file freezes the model of a public model version. If the model code, the seed or the number of paths changes, the command stops. Change `model_version` in `configs/publication.toml` before you make hindcasts with a different model. The new version gets new keys, and the earlier hindcasts stay.

A run can stop and start again. The command does not simulate an origin that has a public document. When only the private output exists, it publishes that output without a new simulation. It writes the series of a season only when every weekly document of the season exists. It then updates the index.

To get the weekly estimates of a club, read `hindcasts/index.json`, then the `series.json` of the division and season. In `series.json`, `origins` lists the origins in time order. Each club in `teams` has one array for each estimate, with one value for each origin in the same order: `played`, `current_points`, `mean_points`, `median_points`, `mean_position`, `median_position`, `position_sd` and `mean_goal_difference`. `events` has one array for each event probability, for example `title_probability`, `promotion_probability` or `relegation_probability`. The weekly document at `href` has the full points and position distributions and their intervals.

Hindcasts do not overwrite the mutable production objects. You do not have to stop production to make them.

## Prospective record

`record.json` keeps one pending last pre-kickoff forecast for each match. As results arrive, the pipeline moves these small records to the settled list and recalculates the summaries. It does not read the forecast archive during a routine run. It reports H/D/A log loss, Brier score and classwise ECE, overall and for each division. The record can be rebuilt from the partitioned competition archives when necessary.

## Viewer

Build a local copy of the sanitized publication surface and start the static viewer:

```sh
uv run epl-forecast materialize --site site
uv run python -m http.server -d site 8000
```

The viewer shows each division's table, position matrix, club distributions, upcoming fixtures, conditional effects and forecast record. Its Hindcasts view shows the weekly hindcast series of one club, season and estimate as a line chart and a table, with the retrospective notice and the information rules. The club page ranks the matches of the week by their effect on that club. It also identifies postponed or undated fixtures.

The default materialization gets `forecasts/current.json`, its four forecast documents and `record.json`. It does not get historical forecasts or hindcasts. Add `--archive eng-league-one` to get one competition archive and its forecast documents for an explicit historical build. Add `--hindcasts` to get the hindcast index, each season series and each weekly hindcast document.

Generated files under `site/data` are not canonical and are not committed. The Pages workflow materializes the private publication bucket into its build artifact, with `--hindcasts`, checks the boundary and deploys the site. The hindcast documents add approximately one minute to the materialization. Both R2 buckets stay private.

The production workflow calls the Pages workflow after a run that publishes at least one forecast. An hourly run that publishes nothing does not deploy. You can also start the Pages workflow manually.

## Credentials

| Secret | Scope | Used by |
| --- | --- | --- |
| `API_FOOTBALL_KEY` | Repository | Production |
| `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | Repository | Production. Object read and write on `page324-data` and `page324-publish`. |
| `R2_PAGES_ACCESS_KEY_ID`, `R2_PAGES_SECRET_ACCESS_KEY` | `github-pages` environment | Pages. Object read only, on `page324-publish` only. |

The variables `R2_ACCOUNT_ID`, `R2_DATA_BUCKET` and `R2_PUBLISH_BUCKET` are repository variables. The Pages workflow does not get the production credential, so the site build cannot read `page324-data`.

To make the Pages credential, create an R2 API token in the Cloudflare dashboard with the "Object Read only" permission, applied to the `page324-publish` bucket only. Then store its access key ID and secret access key:

```sh
gh secret set R2_PAGES_ACCESS_KEY_ID --env github-pages
gh secret set R2_PAGES_SECRET_ACCESS_KEY --env github-pages
```

## Datawrapper proof of concept

This temporary smoke test publishes one ranked chart from the latest Premier League title forecast in `page324-publish`. It is not the chart contract or a production publication pipeline.

Put `DATAWRAPPER_API_KEY` in the ignored `.env` file, then run:

```sh
uv run epl-forecast datawrapper-poc
```

The first run creates a disposable proof-of-concept chart and saves its public chart ID in `configs/datawrapper_poc.toml`. Later runs update and publish the same test chart. The command prints the chart ID, the published URL and the source forecast ID. It stops if the credential or an API step fails.

## Development

```sh
scripts/verify.sh
```

This command formats, lints and tests in that order. The tests use synthetic data and do not need network access.
