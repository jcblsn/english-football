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

Future retrospective forecasts must use the separate `hindcasts/` namespace, so a reader cannot mistake them for forecasts that existed at the historical time.

Historical forecast documents use unique keys. Competition archive indexes, `forecasts/current.json` and `record.json` are mutable.

## Prospective record

`record.json` keeps one pending last pre-kickoff forecast for each match. As results arrive, the pipeline moves these small records to the settled list and recalculates the summaries. It does not read the forecast archive during a routine run. It reports H/D/A log loss, Brier score and classwise ECE, overall and for each division. The record can be rebuilt from the partitioned competition archives when necessary.

## Viewer

Build a local copy of the sanitized publication surface and start the static viewer:

```sh
uv run epl-forecast materialize --site site
uv run python -m http.server -d site 8000
```

The viewer shows each division's table, position matrix, club distributions, upcoming fixtures, conditional effects and forecast record. The club page ranks the matches of the week by their effect on that club. It also identifies postponed or undated fixtures.

The default materialization gets `forecasts/current.json`, its four forecast documents and `record.json`. It does not get historical forecasts. Add `--archive eng-league-one` to get one competition archive and its forecast documents for an explicit historical build.

Generated files under `site/data` are not canonical and are not committed. The Pages workflow materializes the private publication bucket into its build artifact, checks the boundary and deploys the site. Both R2 buckets stay private.

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
