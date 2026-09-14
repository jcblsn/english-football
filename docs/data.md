# Data and provenance

The product uses provider data that stays in the private `page324-data` R2 bucket. Git does not contain provider data. Provider terms control its use and redistribution.

## Providers

| Provider | What the product uses | Divisions |
| --- | --- | --- |
| API-Football | Fixtures, schedules, status, teams and league standings | All four |
| Football-Data | Results and average pre-closing and closing odds | All four |
| Understat | Team xG for each match | Premier League only |
| FPL | Nothing in M7; captured for research | Premier League |

The collector also captures squads, players, lineups, transfers, injuries and match statistics. M7 does not use these inputs. The collector keeps them because a pre-match observation cannot be recovered later. They support research on the [research branch](research.md).

## Credentials and quota

Set `API_FOOTBALL_KEY` and the R2 settings in the environment or in an ignored `.env` file. Do not put a key in a committed file. The Pro plan gives 7,500 requests each day. A backfill keeps 1,000 requests free for current collection.

## Storage

R2 is the durable store. A run uses `data/` only as an ephemeral workspace.

| R2 key | Content |
| --- | --- |
| `raw/<provider>/<hash>` | Raw responses. They are immutable and identified by content hash. |
| `requests/` | One record for each successful request: URL, retrieval time, hash and context. |
| `parquet/<table>/` | Canonical tables, partitioned by competition and season. |
| `manifests/` | Canonical manifests. A Parquet file is visible only after its manifest enters the compact state. |
| `audits/` | Collection status and coverage audits. |
| `state/collection.json` | The latest request for each URL. Routine collection reads this compact state instead of the full request archive. |
| `state/manifests.json` | The canonical manifest catalog. |
| `state/forecast.json` | The last published effective-input fingerprint for each division. |
| `runs/forecasts/` | Private forecast archives, logs and verification reports. |

DuckDB reads canonical Parquet directly from R2 with a temporary in-memory secret. There is no database server and no persistent DuckDB credential. GitHub Actions concurrency stops production jobs from overlapping. The local writer lock also protects one workspace.

## Canonical tables

`src/epl_forecast/datasets.py` defines the schema. The main tables are `competition_seasons`, `teams`, `fixtures`, `odds` and `team_process` (xG). The player tables are `players`, `memberships`, `appearances`, `availability`, `transfers` and `player_process`.

Each row keeps its provider, its actual retrieval time, its evidence basis and the hash of its raw response. `Dataset(root, cutoff)` shows only the evidence retrieved by the cutoff. `Dataset.fixtures()` joins the providers and refuses contradictory identities, dates and scores.

## Identity and reviewed corrections

These files hold reviewed decisions. Change them only with evidence.

| File | Purpose |
| --- | --- |
| `src/epl_forecast/data/teams.csv` | Canonical team IDs and provider names. Extend it; do not invent a slug. |
| `src/epl_forecast/data/api_player_aliases.csv` | Provider player-ID aliases, with same-fixture evidence. |
| `src/epl_forecast/data/api_fixture_disputes.json` | Provider records that contradict other evidence. |
| `src/epl_forecast/data/understat_date_corrections.json` | Understat dates that disagree with the fixture list. |
| `src/epl_forecast/data/pl_adjustments.json` | Reviewed Premier League sanctions and their announcement dates. |
| `src/epl_forecast/data/efl_adjustments.json` | Reviewed EFL sanctions. |
| `src/epl_forecast/data/efl_rules_evidence.json` | Reviewed EFL rules for promotion, playoffs and ties. |

When a source is internally inconsistent, the field becomes unknown and the audit reports it. The code does not normalize the conflict away.

A regular-season match ID is `competition:season:home:away`. A postponement does not change it. Playoff matches have separate IDs. They never enter the regular-season table or model training.

## Commands

```sh
uv run epl-forecast data collect      # capture due observations for all four divisions
uv run epl-forecast data audit        # check hashes and fixtures; write data/audits/coverage.json
uv run epl-forecast data backfill --start 2010 --max-requests 200
uv run epl-forecast data normalize    # rebuild the canonical store from raw captures
uv run epl-forecast data query --sql 'SELECT competition_id, count(*) FROM fixtures GROUP BY 1'
```

`data normalize` replays every raw capture into a new local workspace. It replaces the local canonical files only after the new files pass their checks. Stop scheduled runs first.

A backfill of history is retrospective evidence. It does not show what was known before a historical match. Only prospective captures show that.

## Initial migration

```sh
uv run python scripts/migrate_r2.py
uv run python scripts/migrate_r2.py --include-private-runs
```

The first command copies provider data and publishes the compact state only after the immutable objects exist. The second command also copies retained private forecast runs and snapshots. Both commands are resumable.
