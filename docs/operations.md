# Operations

This page states how the product runs, what it publishes and where it keeps old forecasts. The [product contract](mvp.md) states what each forecast contains.

## One command

```sh
uv run epl-forecast operate
```

`operate` does these steps. It keeps the capture and the private archive in temporary directories that it deletes at the end of the run.

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

## Schedule and refresh rules

`.github/workflows/production.yml` wakes every three hours at 15 minutes after midnight, 03:00, 06:00 and each following three-hour boundary in `America/New_York`. This includes a 09:15 New York run each Saturday and keeps that local time when daylight saving time changes. The workflow also supports manual dispatch. Source refresh intervals are independent of this wake schedule. GitHub Actions concurrency lets one production run finish before another starts.

Fixture lists are eligible each hour. Match details are eligible every 9 minutes in the 75 minutes before kickoff, but the three-hour production schedule can collect them only when a run occurs in that window. The 09:15 New York Saturday run is positioned for the common Saturday match window. During a match, details are eligible each hour. After full time, they have bounded correction checks. A run with no due source sends no request, and a forecast runs only when its effective inputs change. Other sources keep their own intervals.

Each collection run that sends requests to API-Football writes one usage record to `audits/api_football/<UTC timestamp>.json` in `page324-data`. The record has the number of requests and the last daily limit and remaining values from the provider. `audits/collection.json` shows the same values for the most recent run. Use these records to see the real usage over a week.

`audits/collection.json` also has an informational readiness summary. It reports finished matches that still have incomplete xG after three days, Premier League matches in the next seven days that have no market data, and FPL and API-Football availability disagreements in the personnel horizon. These signals do not stop collection, forecasting or publication.

A new forecast is due only when the effective model inputs for that competition or the statistical model code and configuration change. A schedule change in one division does not cause another division to run. Availability and injury data do not change the fingerprint because the structural model does not use them. Publication, site and pipeline code also do not change the statistical fingerprint. A repeated provider response with the same consumed values does not cause publication only because its retrieval time changed.

Routine production does not compact canonical data. Run `uv run python scripts/compact_r2.py` as maintenance after 250 incremental batches collect. The script reads only the R2 catalog. Use `--force` only when an earlier compaction is useful. Compaction keeps row retrieval times, so historical cutoff reads give the same result before and after maintenance. Later routine runs add only new batches to the compact catalog. Compaction does not delete earlier R2 objects. Compaction can run while production collects, because each catalog update is a conditional write that keeps the batches of the other writer.

After a change to the normalization code, run `uv run python scripts/replay_r2.py` and compare the replayed row counts with the current counts. Then run it again with `--publish` to replace the canonical history. See [data](data.md#commands).

GitHub Actions is the normal production writer. The workflow concurrency group prevents two production runs at the same time, but it does not know about local commands. Maintenance and migration writes to R2 must not overlap production. Before such a write, run `gh workflow disable production.yml`, make sure that no production run is in progress, do the write, then run `gh workflow enable production.yml`.

## Versions

A published document carries two version numbers. They answer different questions and they change for different reasons.

| Field | Meaning | Changes when |
| --- | --- | --- |
| `schema_version` | The version of the public contract: which keys a reader of that document kind may expect and how to read them. | A reader that follows the old contract would break. |
| `model_version` | The version of the forecast semantics: what the numbers mean and how they were made. | The model, its inputs or its rules change the numbers. |

A reader that parses documents uses `schema_version`. A reader that compares numbers over time uses `model_version`. One can change without the other: `v0.2` changes the forecast semantics, and it adds the optional `personnel` block without raising any `schema_version`.

Each document kind carries its own `schema_version`. There is no single number for the whole surface, and the numbers do not move together. The private forecast archive that `epl-forecast forecast` writes is a different artifact from the published forecast document, and it keeps its own `schema_version`.

Private forecast schema version 2 retains three explicit match-probability stages: the unadjusted model distribution, the personnel-adjusted score distribution, and the outcome-only market-assisted pool. It retains a score grid for each score-generating stage. Public forecast schema version 3 is unchanged because the public horizon and probability fields did not change.

The `schema_version` of a document stays where it is while every change to that document is additive and optional. The `personnel` block is such a change: it is present only for a Premier League or Championship fixture in the horizon, and a reader that ignores the key still reads a correct and complete forecast. Raise the `schema_version` of a document when a key is removed or renamed, when the type or the meaning of an existing key changes, or when a new key becomes necessary to read the document correctly.

`model_version` in `configs/publication.toml` is the public product version, for example `v0.0`, `v0.1` or `v1.0`. It is separate from the internal model names in `configs/product.toml`, which stay private.

The public version is part of the production fingerprint. When you change it, every division becomes due on the next run, so no current forecast keeps the earlier label. Each forecast document, each pointer and each row in `record.json` keeps the public version that made it. The record summaries can include forecasts from more than one version.

| Version | Changed on `main` | Model change |
| --- | --- | --- |
| `v0.0` | 14 September 2026 | The first public M7 forecasts from R2. |
| `v0.1` | 15 September 2026 | The National League became an entry source for clubs promoted to League Two, and M7 observed API-Football team xG in every division. |
| `v0.2` | 15 September 2026 | Premier League and Championship fixtures in the next six days get a temporary matchday-squad continuity adjustment. The persistent M7 state does not change. See [methodology](methodology.md#matchday-squad-continuity) and [validation](validation.md#matchday-squad-continuity). |
| `v0.2.1` | 16 September 2026 | A usable FPL availability status takes priority over API-Football for a Premier League player. Repeated captures of one transfer event count as one membership reason. |
| `v0.3.0` | Not yet merged | M10 replaces M7. Club Quality is a persistent level, which does not return to the league mean, plus a form that returns to the level. See [methodology](methodology.md#dynamics) and [validation](validation.md#m10-quality-dynamics). |

A new version needs new hindcasts. The hindcast edition of a version freezes its model code, so the `v0.1` hindcasts cannot describe `v0.2`.

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
- for each Premier League and Championship fixture in the next six days, the matchday-squad discontinuity of each club and the home log-rate shift;
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

The command makes hindcasts for the four divisions in 2021/22–2025/26. Use `--competition` and `--seasons` to make a part of the archive. The command reads the canonical history from `page324-data`.

The rules for each hindcast:

- There is one origin each Wednesday at 09:00 Europe/London. The first origin is the Wednesday on or before the first regular-season match. The last origin is the first Wednesday after the last result. The archive keeps every weekly origin, also when the estimates do not change. The origin is a London wall-clock time, so it keeps its local hour across a daylight-saving change and its UTC instant moves.
- The model uses the results of matches played before the London day of the origin. It uses the same information rules as the [season panels](validation.md#method): results and xG are available on the day after each match, a points deduction applies from its reviewed announcement date, and the simulation uses the fixture dates that the season finally used.
- The structural model makes the season simulation. A hindcast has no market-assisted probabilities, no match impacts and no score grids.
- Each document lists these assumptions in `assumptions`, and has `"product": "hindcast"` and `"retrospective": true`.

### The origin protocol

The weekday and time of the origin are an observation protocol. They decide when a retrospective forecast is taken. They do not change how the model forecasts, so a change of weekday is not evidence that the model became better or worse. Do not compare a Wednesday edition with a Monday edition and read the difference as a model effect.

`v0.2` and later editions use Wednesday. `v0.0` used Monday. That edition is immutable and keeps its Monday origins. An edition file from `v0.2` onward records `origin_weekday`, `origin_time` and `origin_time_zone`, so a reader does not have to read the code of the version that made it. The `v0.0` edition predates those fields: it states its protocol only in the free text of `origin_rule`. `claim_edition` compares the whole edition, so a rerun of an older version with the new weekday stops instead of extending that archive with origins it never had.

`v0.1` has no hindcast archive and no edition file. It was the published version for about one day before `v0.2` replaced it.

If a same-origin comparison between two model versions is ever needed, generate the older version again under its own separately identified edition. Do not write Wednesday origins into the `v0.0` archive.

The command writes these objects:

| Bucket | Key | Content |
| --- | --- | --- |
| `page324-data` | `runs/hindcasts/<version>/edition.json` | The model code hashes, the seed, the number of paths and the origin protocol of the public model version: the rule, the weekday, the time and the time zone. It is immutable. |
| `page324-data` | `runs/hindcasts/<version>/<competition>/<season>/<hindcast>.json` | The private simulation output of one origin. It is immutable. |
| `page324-publish` | `hindcasts/<version>/<competition>/<season>/<hindcast>.json` | The sanitized season estimates of each club at one origin. It is immutable. |
| `page324-publish` | `hindcasts/<version>/<competition>/<season>/series.json` | The weekly series of the season. |
| `page324-publish` | `hindcasts/index.json` | One row for each public model version, division and season, with a link to its series. |

The hindcast ID is the origin time in UTC, in the same form as a forecast ID. `origin_at` gives the origin in London time.

The edition file freezes the model of a public model version. If the model code, the seed or the number of paths changes, the command stops. Change `model_version` in `configs/publication.toml` before you make hindcasts with a different model. The new version gets new keys, and the earlier hindcasts stay.

A run can stop and start again. The command does not simulate an origin that has a public document. When only the private output exists, it publishes that output without a new simulation. It writes the series of a season only when every weekly document of the season exists. It then updates the index.

To get the weekly estimates of a club, read `hindcasts/index.json`, then the `series.json` of the division and season. In `series.json`, `origins` lists the origins in time order. Each club in `teams` has one array for each estimate, with one value for each origin in the same order: `played`, `current_points`, `mean_points`, `median_points`, `mean_position`, `median_position`, `position_sd` and `mean_goal_difference`. `points_intervals` and `position_intervals` have one `[low, high]` pair for each origin at the 50%, 80% and 90% levels. `events` has one array for each event probability, for example `title_probability`, `promotion_probability` or `relegation_probability`. The weekly document at `href` has the full points and position distributions and their intervals.

Hindcasts do not overwrite the mutable production objects. You do not have to stop production to make them.

## Prospective record

`record.json` keeps one pending last pre-kickoff forecast for each match. As results arrive, the pipeline moves these small records to the settled list and recalculates the summaries. It does not read the forecast archive during a routine run. It reports H/D/A log loss, Brier score and classwise ECE, overall and for each division. The record can be rebuilt from the partitioned competition archives when necessary.

## Viewer

Build a local copy of the sanitized publication surface and start the static viewer:

```sh
uv run epl-forecast materialize --site site
uv run python -m http.server -d site 8000
```

The viewer shows each division's table, position matrix, club distributions, upcoming fixtures, conditional effects and forecast record. Its Hindcasts view shows the weekly hindcast series of one club, season and estimate as a line chart and a table, with the central 80% interval for expected points and expected position, with the retrospective notice and the information rules. The club page ranks the matches of the week by their effect on that club. It also identifies postponed or undated fixtures.

The default materialization gets `forecasts/current.json`, its four forecast documents and `record.json`. It does not get historical forecasts or hindcasts. Add `--archive eng-league-one` to get one competition archive and its forecast documents for an explicit historical build. Add `--hindcasts` to get the hindcast index, each season series and each weekly hindcast document.

Generated files under `site/data` are not canonical and are not committed. The Pages workflow materializes the private publication bucket into its build artifact, with `--hindcasts`, checks the boundary and deploys the site. The hindcast documents add approximately one minute to the materialization. Both R2 buckets stay private.

The production workflow calls the Pages workflow after a run that publishes at least one forecast. A run that publishes nothing does not deploy, so most of the three-hour wakes deploy nothing. You can also start the Pages workflow manually.

## Credentials

| Secret | Scope | Used by |
| --- | --- | --- |
| `API_FOOTBALL_KEY` | Repository | Production |
| `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | Repository | Production and Pages. Object read and write on `page324-data` and `page324-publish`. |

The variables `R2_ACCOUNT_ID`, `R2_DATA_BUCKET` and `R2_PUBLISH_BUCKET` are repository variables. The Pages workflow uses the same credential as production. It gets only `R2_PUBLISH_BUCKET`, and it reads only `page324-publish`. The credential itself can also read and write `page324-data`, so a change to the Pages workflow needs the same review as a change to production.

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
