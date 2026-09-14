# Operations

This page states how the product runs, what it publishes and where old forecasts are kept. The [product contract](mvp.md) states what each forecast contains.

## One command

```sh
uv run epl-forecast operate
```

`operate` does these steps:

1. It collects new provider data for all four divisions.
2. It runs the M7 forecast for each division, with one shared cutoff.
3. It verifies each archive against the product contract.
4. It publishes only if every archive passes.
5. It writes the public documents, the snapshot index and the prospective ledger.

A failed or unverified run publishes nothing. Its private files stay under `runs/product/<snapshot>/` for inspection.

| Option | Effect |
| --- | --- |
| `--force` | Run even if no new information arrived. |
| `--no-collect` | Use the data archive as it is. |
| `--interval-hours 12` | Run when the information changes or this time has passed. |
| `--simulations 10000` | Number of season paths. The publication floor is 1,000. |
| `--site`, `--runs`, `--data` | Other locations for the site, private runs and data. |

## Schedule

```sh
uv run epl-forecast operate --install-launch-agent
```

This installs the macOS launch agent `org.epl-forecast.operate`. It runs `operate` every twelve hours and writes `runs/product/operate.log`. To remove it:

```sh
launchctl bootout gui/$UID/org.epl-forecast.operate
```

Stop the agent before you work on the data layer, because it takes the writer lock.

## Single steps

```sh
uv run epl-forecast forecast --competition eng-league-one --output runs/check/l1
uv run epl-forecast verify --archive runs/check/l1 --output runs/check/l1-verification
```

`forecast` writes a private archive: `forecast.json`, `run.json`, CSV tables and an HTML page. `verify` writes `verification.json` and fails if any check fails.

## What may be published

`configs/publication.toml` is the boundary. It lists every key that may appear in a published document. It also lists key parts and value patterns that must never appear, for example provider names, file paths and odds.

The code enforces the boundary three times:

1. It builds each document from the allowlist.
2. It checks each document before it writes it.
3. `scripts/check_publishable.py` checks the whole committed site in CI.

Published:

- H/D/A probabilities and the market-assisted probability;
- exact-score grids for each club's next fixture;
- points and position distributions, with their intervals;
- event probabilities, and the conditional impact of each match of the week on every club;
- the list of postponed or undated fixtures;
- timestamps, model identity and the verification result.

Private:

- all of `data/`, `runs/` and `snapshots/`;
- provider payloads, odds and request records;
- file hashes and the full run provenance.

## Snapshot archive

The pipeline writes each snapshot once, to `site/data/forecasts/<snapshot>/<competition>.json`. It never rewrites a snapshot. `site/data/index.json` lists every snapshot, newest first. These snapshots are the public record of the product. Do not change or delete them. Each division publishes on its own: if one division fails, the snapshot holds the divisions that pass, the pipeline reports `partial`, and the next run tries the division that failed again.

Each document measures every match of the week against every club. The impact rows are grouped by event, as parallel arrays of club IDs and probabilities. A record for each club and each event makes that block approximately four times larger. In the measured snapshot of 2026-09-11, the block holds 857 Premier League rows in 112 KiB and 1,728 League Two rows in 219 KiB. The documents are 223 KiB and 366 KiB. A club whose expected movement is less than 0.005 percentage points has no row; its event probability stays with the club in the same document.

To rebuild `site/data` from the private archives:

```sh
uv run python scripts/backfill_publication.py
```

It verifies each archive under `runs/product/` as it is and publishes the ones that pass. It reports an archive that fails. It does not repair it.

## Prospective ledger

`site/data/ledger.json` scores each settled match once. It uses the last snapshot made before the kickoff. It reports H/D/A log loss, Brier score and classwise ECE, overall and for each division. The pipeline rebuilds the ledger on every run.

## Viewer

`site/` is a static page. It reads only the published JSON.

```sh
uv run python -m http.server -d site 8000
```

It shows each division's table, the position matrix, club distributions, upcoming fixtures, conditional impacts and the ledger. The club page also ranks the matches of the week by their effect on that club. It shows a note for each postponed or undated fixture.

## Hosting

GitHub Actions runs the checks on every push and pull request. The Pages workflow in `.github/workflows/pages.yml` runs only by hand. It publishes `site/` as committed, after the boundary check. To make the site public, enable Pages for the repository and add a push trigger. Forecasts are not made in CI, because they need the private data archive.

## Datawrapper proof of concept

This temporary smoke test checks the Datawrapper connection and API syntax. It publishes one ranked chart from the latest Premier League title forecast. It is not the chart contract or a production publication pipeline. The committed forecast JSON remains the source of truth.

Put `DATAWRAPPER_API_KEY` in the ignored `.env` file, then run:

```sh
uv run epl-forecast datawrapper-poc
```

The first run creates a disposable proof-of-concept chart and saves its public chart ID in `configs/datawrapper_poc.toml`. This ID only prevents duplicate test charts. It does not identify a required chart for a future product. Later runs update and publish the same test chart. The command prints the chart ID, the published URL and the source snapshot ID. It stops with an error if the credential or an API step fails.

## Development

```sh
scripts/verify.sh
```

This formats, lints and tests, in that order. The tests use synthetic data and need no network.
