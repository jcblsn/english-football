# Operations

This page states how the product runs, what it publishes and where it keeps old forecasts. The [product contract](mvp.md) states what each forecast contains.

## One command

```sh
uv run epl-forecast operate
```

`operate` does these steps:

1. It loads compact operational state from `page324-data`.
2. It collects each data source when that source is eligible.
3. It uploads only the raw payloads and canonical batches created in this run. It updates the state that makes them visible only after those objects exist.
4. It calculates a fingerprint from the effective model inputs and the forecast code and configuration.
5. It runs each division whose last successful fingerprint differs.
6. It verifies each private forecast archive against the product contract.
7. It uploads the private archive to `page324-data`.
8. It writes each verified public document to `page324-publish`, then updates the forecast index and prospective record.

A failed or unverified division does not publish. Other verified divisions in the same run can publish and advance their own latest pointers. The next run retries only the divisions that do not have the current successful fingerprint.

| Option | Effect |
| --- | --- |
| `--force` | Run even if the effective inputs did not change. |
| `--no-collect` | Use the canonical archive as it is. |
| `--simulations 10000` | Set the number of season paths. The publication floor is 1,000. |
| `--site`, `--runs`, `--data` | Set ephemeral workspace locations. |

## Schedule and refresh rules

`.github/workflows/production.yml` wakes at 17 minutes after each hour and also supports manual dispatch. Source refresh intervals are independent of this wake schedule. GitHub Actions concurrency lets one production run finish before another starts.

Fixture lists are eligible each hour. Match details are eligible every 15 minutes near kickoff and have bounded correction checks after full time. Other sources keep their own intervals.

A new forecast is due only when effective model inputs or forecast code and configuration change. A repeated provider response with the same consumed values does not cause publication only because its retrieval time changed.

Routine production does not compact canonical data. Run `uv run python scripts/compact_r2.py` as maintenance after 250 incremental batches collect. Use `--force` only when an earlier compaction is useful. Compaction keeps row retrieval times, so historical cutoff reads give the same result before and after maintenance.

## Single steps

```sh
uv run epl-forecast forecast --competition eng-league-one --output runs/check/l1
uv run epl-forecast verify --archive runs/check/l1 --output runs/check/l1-verification
```

`forecast` writes a private archive: `forecast.json`, `run.json`, CSV tables and an HTML page. `verify` writes `verification.json` and fails if any check fails.

## Publication boundary

`configs/publication.toml` lists every key that can appear in a published document. It also lists key parts and value patterns that must not appear, such as provider names, file paths and odds.

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

The pipeline writes each live forecast once to `forecasts/<run>/<competition>.json` in `page324-publish`. It then updates `forecasts/index.json`. The index lists history and the latest successful forecast for each division. Verified forecasts from one run share a run identity.

The separate `hindcasts/` namespace has its own index. It is empty in this batch. Future retrospective forecasts must use that namespace, so a reader cannot mistake them for forecasts that existed at the historical time.

Historical forecast documents use unique keys. The two indexes, per-division latest pointers and `record.json` are mutable.

## Prospective record

`record.json` scores each settled match once. It uses the last live forecast made before kickoff. It reports H/D/A log loss, Brier score and classwise ECE, overall and for each division. This record starts fresh with the production publication surface.

## Viewer

Build a local copy of the sanitized publication surface and start the static viewer:

```sh
uv run epl-forecast materialize --site site
uv run python -m http.server -d site 8000
```

The viewer shows each division's table, position matrix, club distributions, upcoming fixtures, conditional effects and forecast record. The club page ranks the matches of the week by their effect on that club. It also identifies postponed or undated fixtures.

Generated files under `site/data` are not canonical and are not committed. The Pages workflow materializes the private publication bucket into its build artifact, checks the boundary and deploys the site. Both R2 buckets stay private.

## Datawrapper proof of concept

This temporary smoke test publishes one ranked chart from the latest Premier League title forecast in `page324-publish`. It is not the chart contract or a production publication pipeline.

Put `DATAWRAPPER_API_KEY` in the ignored `.env` file, then run:

```sh
uv run epl-forecast datawrapper-poc
```

The first run creates a disposable proof-of-concept chart and saves its public chart ID in `configs/datawrapper_poc.toml`. Later runs update and publish the same test chart. The command prints the chart ID, the published URL and the source run ID. It stops if the credential or an API step fails.

## Development

```sh
scripts/verify.sh
```

This command formats, lints and tests in that order. The tests use synthetic data and do not need network access.
