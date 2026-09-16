# Data and provenance

The product uses provider data that stays in the private `page324-data` R2 bucket. Git does not contain provider data. Provider terms control its use and redistribution.

## Providers

| Provider | What the product uses | Divisions |
| --- | --- | --- |
| API-Football | Fixtures, schedules, status, teams, league standings and team xG | All four |
| Football-Data | Results and average pre-closing and closing odds | All four forecast divisions; National League results as entry-prior evidence only |
| API-Football xG | Team xG for each match, from the first match with xG in each division | All four |
| Understat | Team xG for each match before API-Football xG starts | Premier League only |
| FPL | Player status and club for the matchday-squad continuity adjustment | Premier League |

The collector also captures squads, players, lineups, transfers, injuries and match statistics. The matchday-squad continuity adjustment uses lineups, squads, transfers and injuries. The persistent M7 state does not use these inputs. The collector keeps them because a pre-match observation cannot be recovered later. They support research on the [research branch](research.md).

The National League is an entry-source competition. The collector retains its historical Football-Data results so that the generic entry-prior model can use a complete source season for a club promoted to League Two. National League matches do not update the League Two filter. The product does not forecast or publish the National League.

## Credentials and quota

Set `API_FOOTBALL_KEY` and the R2 settings in the environment or in an ignored `.env` file. Do not put a key in a committed file. The Pro plan gives 7,500 requests each day. A backfill keeps 1,000 requests free for current collection.

## Storage

R2 is the durable store and the authoritative history. A run uses `data/` only as an ephemeral workspace.

A historical run, for example a hindcast or a season panel, must read the canonical history from `page324-data`. Give it an empty workspace, such as a new directory under `runs/`. Do not use files that an earlier run left in the repository `data/` directory as input. `Dataset` reads local manifests together with the R2 catalog, so an old local workspace can change the history that a run sees.

| R2 key | Content |
| --- | --- |
| `raw/<provider>/<hash>` | Raw responses. They are immutable and identified by content hash. |
| `requests/` | One record for each successful request: URL, retrieval time, hash and context. |
| `parquet/<table>/` | Canonical tables, partitioned by competition and season. |
| `manifests/` | Canonical manifests. A Parquet file is visible only after its manifest enters the compact state. |
| `audits/` | Collection status and coverage audits. |
| `state/collection.json` | The latest request for each URL. Routine collection reads this compact state instead of the full request archive. |
| `state/manifests.json` | The compact retained base and the canonical batches collected after it. |
| `state/forecast.json` | The last published effective-input fingerprint for each division. |
| `runs/forecasts/` | Private forecast archives, logs and verification reports. |
| `runs/hindcasts/` | The private simulation output of each weekly hindcast and the frozen model of each public model version. See [operations](operations.md#hindcasts). |

DuckDB reads canonical Parquet directly from R2 with a temporary in-memory secret. There is no database server and no persistent DuckDB credential. GitHub Actions concurrency stops production jobs from overlapping. The local writer lock also protects one workspace.

## Canonical tables

`src/epl_forecast/datasets.py` defines the schema. The main tables are `competition_seasons`, `teams`, `fixtures`, `odds`, `team_statistics` (API-Football xG) and `team_process` (Understat xG). The player tables are `players`, `memberships`, `appearances`, `availability`, `transfers` and `player_process`. `source_snapshots` records which provider responses a reader has seen.

Each row keeps its provider, its actual retrieval time, its evidence basis and the hash of its raw response. `Dataset(root, cutoff)` shows only the evidence retrieved by the cutoff. `Dataset.fixtures()` joins the providers and refuses contradictory identities, dates and scores.

## Source snapshots

`source_snapshots` holds one row for each successful retrieval of one query scope: a club squad, the injury list of a competition season, the FPL availability of a season, the detail of one fixture, or the history of one player or club. The row exists even when the response held no rows.

The row is what makes an empty response readable. Without it, a reader cannot tell "the provider listed nobody" from "the provider was never asked", so an empty response would silently leave the previous one in force. The knowledge cannot live in the request manifests, because canonical compaction keeps rows and collapses request contexts. It is a canonical row, so it compacts like any other.

`epl_forecast.snapshots` selects the one latest snapshot of a scope at a cutoff, ordered by retrieval time and then by content hash. Every reader uses that one selector, so the personnel evidence and the FPL ingestion cannot define "the latest captured squad" differently.

Snapshot rows are written when a response is normalized. Retained captures from before this table existed have no snapshot rows. `uv run epl-forecast data normalize` replays every raw capture and creates them. Until that replay runs against a workspace, a reader of that history sees no squad, injury or FPL scope and falls back to membership from matchday squads alone, which is what a hindcast already does.

## Production contracts of the player tables

These four tables now change published forecasts, through the matchday-squad continuity adjustment. Their contracts:

| Table | What a row asserts | What it does not assert |
| --- | --- | --- |
| `appearances` | The provider reported this player in the matchday squad of this club in this match at this retrieval, with the minutes it recorded. | That the squad is complete. A capture before kickoff is a team sheet only when it names 11 starters and at least 7 substitutes. |
| `memberships` with `basis='captured_squad'` | This player was in the squad the provider published for this club at this retrieval. | Membership at any other time. Absence from one snapshot is not a transfer. |
| `availability` | The provider reported this status for this player, in the scope named by `scope` and `competition_id`. | Anything about a player it does not name. Absence is not proof of availability. |
| `transfers` | The provider dated a move of this player between these clubs. | A complete transfer history. Two moves dated the same day are not ordered by the evidence. |

Reading rules that follow from these contracts:

- Read squads, injury lists and FPL statuses through `source_snapshots`, never by taking the latest row of the table. The scope of an injury response is a competition and a season together, so a response retrieved later for an earlier season may not supersede the current one.
- For a completed match, take the participants and the minutes of a club from one latest usable capture. A capture that records no minutes is not usable, so a short later response cannot erase a complete earlier one.
- Treat rows retrieved after the forecast cutoff as invisible. A later observation may never change an earlier forecast.

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
uv run epl-forecast data collect      # capture due forecast and entry-source observations
uv run epl-forecast data audit        # check hashes and fixtures; write data/audits/coverage.json
uv run epl-forecast data backfill --start 2010 --max-requests 200
uv run epl-forecast data normalize    # rebuild the canonical store from raw captures
uv run epl-forecast data query --sql 'SELECT competition_id, count(*) FROM fixtures GROUP BY 1'
```

`data normalize` replays every raw capture into a new local workspace. It replaces the local canonical files only after the new files pass their checks. Stop scheduled runs first.

Routine synchronization uploads only objects from the current collection. It does not list the full bucket. Canonical compaction is a maintenance task, not part of each collection. Run `uv run python scripts/compact_r2.py` after the incremental-batch threshold is reached. The default threshold is 250 batches.

A backfill of history is retrospective evidence. It does not show what was known before a historical match. Only prospective captures show that.
