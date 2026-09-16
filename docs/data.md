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

The collector also captures squads, players, lineups, transfers, injuries and match statistics. The matchday-squad continuity adjustment uses lineups, squads, transfers and injuries. The persistent M7 state does not use these inputs. The collector keeps them because a pre-match observation cannot be recovered later. They also support research on the [research branch](research.md).

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
| `state/impacts.json` | For each match of the week, the conditional-impact record of the last forecast made before its kickoff. The published forecast carries it after the result is known. |
| `runs/forecasts/` | Private forecast archives, logs and verification reports. |
| `runs/hindcasts/` | The private simulation output of each weekly hindcast and the frozen model of each public model version. See [operations](operations.md#hindcasts). |

DuckDB reads canonical Parquet directly from R2 with a temporary in-memory secret. There is no database server and no persistent DuckDB credential. GitHub Actions concurrency stops production jobs from overlapping. The local writer lock also protects one workspace.

## Canonical tables

`src/epl_forecast/datasets.py` defines the schema. The main tables are `competition_seasons`, `teams`, `fixtures`, `odds`, `team_statistics` (API-Football xG) and `team_process` (Understat xG). The player tables are `players`, `memberships`, `appearances`, `availability`, `transfers` and `player_process`. `source_snapshots` records which provider responses a reader has seen.

Each row keeps its provider, its actual retrieval time, its evidence basis and the hash of its raw response. `Dataset(root, cutoff)` shows only the evidence retrieved by the cutoff. `Dataset.fixtures()` joins the providers and refuses contradictory identities, dates and scores.

## Source snapshots

`source_snapshots` holds one row for each successful retrieval of one query scope: a club squad, the injury list of a competition season, the FPL availability of a season, the detail of one club in one fixture, or the history of one player or club. The row exists even when the response held no rows.

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
uv run epl-forecast data ui           # open the prepared local DuckDB UI
uv run epl-forecast data query --sql 'SELECT competition_id, count(*) FROM analysis.matches GROUP BY 1'
```

`data normalize` replays every raw capture into a new local workspace. It replaces the local canonical files only after the new files pass their checks. Stop scheduled runs first.

Routine synchronization uploads only objects from the current collection. It does not list the full bucket. Canonical compaction is a maintenance task, not part of each collection. Run `uv run python scripts/compact_r2.py` after the incremental-batch threshold is reached. The default threshold is 250 batches.

A backfill of history is retrospective evidence. It does not show what was known before a historical match. Only prospective captures show that.

## Interactive analysis

Run `uv run epl-forecast data ui`. The command opens one in-memory DuckDB connection, loads the `analysis` schema, and starts the DuckDB UI on that same connection. The process must stay open while you use the UI. Press Control-C in the terminal to stop the UI and close the connection.

Use `uv run epl-forecast data ui --no-browser` to start the local server without opening a browser. The default address is `http://localhost:4213`.

The UI runs queries on the local DuckDB process. It does not use MotherDuck unless you explicitly enable MotherDuck. The command creates temporary R2 secrets with separate scopes for `page324-data` and `page324-publish`. It does not store credentials in a DuckDB database.

`data query` uses the same analysis-session bootstrap. Use `--cutoff` to set the canonical evidence cutoff:

```sh
uv run epl-forecast data query --cutoff 2026-08-15T12:00:00+00:00 --sql 'SELECT season_id, count(*) AS matches FROM analysis.matches GROUP BY 1 ORDER BY 1'
```

The session reads the canonical manifest catalog from R2 and does not read local manifests or local canonical files. The `--root` option remains for command compatibility, but it cannot add local evidence to an analysis session. Raw canonical and provider views remain available for expert use.

The first session can take longer because it validates and normalizes the indexed history. The ignored `runs/analysis-cache/` directory holds rebuildable copies of immutable JSON artifacts and normalized Parquet tables. The cache identity includes the canonical manifest set, the evidence cutoff, forecast archive entries, hindcast series entries, and the prospective record. R2 indexes remain authoritative. A new indexed artifact is normalized and added to the prior cache; it does not make the session discover bucket objects by prefix.

### Analysis catalog

Start with the catalog:

```sql
SELECT object_name, grain, temporal_semantics, private, caveats
FROM analysis.catalog
ORDER BY object_name;
```

`analysis.session` records the canonical evidence cutoff, manifest identity, loaded manifest batches, publication-index timestamps, and loaded public model versions.

The main canonical relations are:

| Relation | Grain | Important rule |
| --- | --- | --- |
| `analysis.matches` | One row for each `match_id` | It is the materialized result of `Dataset.fixtures()`. It reconciles providers and rejects contradictions. The raw `fixtures` view does not have this grain. |
| `analysis.team_matches` | Two rows for each match | It gives team, opponent, venue, result, and goals in team-oriented form. |
| `analysis.team_match_xg` | One row for each match with preferred xG for both teams | It is the materialized result of `Dataset.xg_observations()` and uses the product transition from Understat to API-Football xG. |
| `analysis.player_matches` | One row for each player, team, match, and provider capture | It keeps capture identity. Select one response explicitly when a query needs one capture. |
| `analysis.personnel_snapshots` | One row for each latest successful query scope | It includes successful responses that returned no rows. |
| `analysis.squad_memberships`, `analysis.injury_availability`, `analysis.fpl_availability` | Rows from the latest successful snapshot, or one row with a null player for an empty response | A null player with `row_count=0` is evidence that the provider returned an empty response. |

For example, this query gives team results with preferred xG when xG exists:

```sql
SELECT tm.competition_id, tm.season_id, tm.match_date, tm.team_id, tm.opponent_id, tm.result,
       CASE WHEN tm.venue = 'home' THEN x.home_xg ELSE x.away_xg END AS xg_for,
       CASE WHEN tm.venue = 'home' THEN x.away_xg ELSE x.home_xg END AS xg_against
FROM analysis.team_matches tm
LEFT JOIN analysis.team_match_xg x USING (match_id)
WHERE tm.status = 'finished'
ORDER BY tm.match_date DESC, tm.match_id, tm.venue;
```

### Live forecasts

`analysis.forecasts` has one row for each successful public forecast and competition. The competition archive is the authoritative list. A failed attempt or a private run that did not enter the archive is not in this relation. Each row links to the expected private run.

`analysis.forecast_matches` has the complete modeled match set from the private run. `on_public_surface` says whether the public forecast included that match in its short horizon. The `structural_p_*` columns are separate from the optional `market_assisted_p_*` columns. The season simulation uses the structural model.

```sql
SELECT f.generated_at, m.match_id, m.on_public_surface,
       m.structural_p_home, m.structural_p_draw, m.structural_p_away,
       m.market_assisted_p_home, m.market_assisted_p_draw, m.market_assisted_p_away
FROM analysis.forecast_matches m
JOIN analysis.forecasts f USING (forecast_id, competition_id, season_id)
WHERE f.competition_id = 'eng-premier-league'
ORDER BY f.generated_at DESC, m.match_date
LIMIT 100;
```

`analysis.forecast_teams` has scalar season estimates. The event, points-distribution, position-distribution, and interval relations are long-form children. `analysis.model_team_states` and `analysis.forecast_runs` are private. They keep stable common fields and JSON columns for model-specific state, diagnostics, and provenance. `analysis.forecast_impacts` is long-form by match, event, team, and outcome, with carry-forward fields.

### Hindcasts and timing

`analysis.hindcast_origins` and its child relations come only from `hindcasts/index.json` and the season series to which it points. Every origin has `retrospective=true`. `origin_at` is the simulated historical origin. It is not the time at which the artifact existed. `generated_at` is null by design.

`analysis.team_projections` is a convenience union of live and hindcast team estimates. Do not replace its explicit time fields with one generic `as_of` value:

```sql
SELECT product, retrospective, generated_at, origin_at, state_observed_at,
       model_results_cutoff, competition_id, season_id, team_id, mean_points, mean_position
FROM analysis.team_projections
WHERE team_id = 'arsenal'
ORDER BY coalesce(generated_at, origin_at);
```

An evidence cutoff applies to canonical rows through `retrieved_at`. It does not remove derived artifacts by their generation time. A live forecast has an actual `generated_at`, a `state_observed_at`, and a `model_results_cutoff`. A hindcast has a retrospective `origin_at` and a model-results cutoff. These fields are not interchangeable.

### Prospective scoring

`analysis.record_matches` reproduces the pending and settled last-pre-kickoff rows in `record.json`. `analysis.record_summary` gives the overall and competition scoring summaries and keeps the complete summary block in `metrics`.

```sql
SELECT competition_id, outcome, count(*) AS matches,
       avg(-ln(CASE outcome WHEN 'H' THEN p_home WHEN 'D' THEN p_draw ELSE p_away END)) AS log_loss
FROM analysis.record_matches
WHERE record_state = 'settled'
GROUP BY 1, 2
ORDER BY 1, 2;
```
