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

The collector also captures squads, players, lineups, transfers, injuries and match statistics. The matchday-squad continuity adjustment uses lineups, squads, transfers and injuries. The persistent M10 state does not use these inputs. The collector keeps them because a pre-match observation cannot be recovered later. They also support research on the [research branch](research.md).

The National League is an entry-source competition. The collector retains its historical Football-Data results so that the generic entry-prior model can use a complete source season for a club promoted to League Two. National League matches do not update the League Two filter. The product does not forecast or publish the National League.

## Credentials and quota

Set `API_FOOTBALL_KEY` and the R2 settings in the environment or in an ignored `.env` file. Do not put a key in a committed file. The Pro plan gives 7,500 requests each day.

## Storage

R2 is the durable store and the only source of canonical evidence. There is no local data directory, and no command accepts a data workspace path.

`Dataset` reads the canonical catalog and Parquet files from `page324-data`. Collection is the only exception. `operate` captures new responses into a temporary workspace that it creates for that run. During the capture, `Dataset` also reads the batches in that workspace that are not yet in the R2 catalog. A workspace file never replaces an R2 file. The run uploads the new objects to R2 and then deletes the workspace.

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

DuckDB reads canonical Parquet directly from R2 with a temporary in-memory secret. There is no database server and no persistent DuckDB credential. GitHub Actions concurrency stops production jobs from overlapping.

The catalogs `state/manifests.json` and `state/collection.json` are the only mutable objects that collection and compaction share. Each update reads the object and its ETag, applies the change to that version, and writes with a condition on the ETag. When another writer changed the object first, R2 refuses the write, and the update starts again from the new version. Two writers therefore cannot remove each other's batches or request records. Compaction keeps the batches that arrive while it runs.

## Canonical tables

`src/epl_forecast/datasets.py` defines the schema. The main tables are `competition_seasons`, `teams`, `fixtures`, `odds`, `team_statistics` (API-Football xG) and `team_process` (Understat xG). The player tables are `players`, `memberships`, `appearances`, `availability`, `transfers` and `player_process`. `source_snapshots` records which provider responses a reader has seen.

Each row keeps its provider, its actual retrieval time, its evidence basis and the hash of its raw response. `Dataset(root, cutoff)` shows only the evidence retrieved by the cutoff. `Dataset.fixtures()` joins the providers and refuses contradictory identities, dates and scores.

## Source snapshots

`source_snapshots` holds one row for each successful retrieval of one query scope: a club squad, the injury list of a competition season, the FPL availability of a season, the detail of one club in one fixture, or the history of one player or club. The row exists even when the response held no rows.

The row is what makes an empty response readable. Without it, a reader cannot tell "the provider listed nobody" from "the provider was never asked", so an empty response would silently leave the previous one in force. The knowledge cannot live in the request manifests, because canonical compaction keeps rows and collapses request contexts. It is a canonical row, so it compacts like any other.

`epl_forecast.snapshots` selects the one latest snapshot of a scope at a cutoff, ordered by retrieval time and then by content hash. Every reader uses that one selector, so the personnel evidence and the FPL ingestion cannot define "the latest captured squad" differently.

Snapshot rows are written when a response is normalized. A capture that no replay has normalized since this table was added has no snapshot rows. A reader of that history sees no squad, injury or FPL scope and falls back to membership from matchday squads alone, which is what a hindcast already does.

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
uv run epl-forecast data audit        # check R2 hashes and fixtures; write audits/coverage.json to R2
uv run epl-forecast data ui           # open the prepared local DuckDB UI
uv run epl-forecast data query --sql 'SELECT competition_id, count(*) FROM analysis.matches GROUP BY 1'
```

`operate` is the only command that collects.

After a change to the normalization code, replay the retained raw captures:

```sh
uv run python scripts/replay_r2.py            # report only
uv run python scripts/replay_r2.py --publish  # replace the canonical history
```

The replay reads every request record and its raw capture from R2 into a temporary workspace. It stops when a raw capture does not match the hash in its request record. It normalizes the captures in a fixed order with the current code. During normalization, it hides the R2 settings, so the normalizers read only the replayed rows and not the old canonical rows. It then checks the hashes and the fixtures of the result. Without `--publish`, it prints the distinct row count of each table for the replay and for the current catalog, and writes nothing. With `--publish`, it writes the replay as one base batch. The catalog update replaces only the batches that the replay read at its start, and keeps the batches that collection adds while it runs. The replay does not send a provider request.

`data audit` reads the whole canonical history from R2, so it takes minutes. Its report shows the history at the time of the audit.

Routine synchronization uploads only objects from the current collection. It does not list the full bucket. Canonical compaction is a maintenance task, not part of each collection. Run `uv run python scripts/compact_r2.py` after the incremental-batch threshold is reached. The default threshold is 250 batches.

Captured history is retrospective evidence. It does not show what was known before a historical match. Only prospective captures show that.

## Interactive analysis

Run `uv run epl-forecast data ui`. The command prepares the `analysis` schema, opens one read-only connection to the session file, and starts the DuckDB UI on that same connection. The process must stay open while you use the UI. Press Control-C in the terminal to stop the UI and close the connection.

Use `uv run epl-forecast data ui --no-browser` to start the local server without opening a browser. The default address is `http://localhost:4213`.

The UI runs queries on the local DuckDB process. It does not use MotherDuck unless you explicitly enable MotherDuck. The command uses temporary R2 secrets with separate scopes for `page324-data` and `page324-publish` only while it prepares the session file. It does not store credentials in the session file.

`data query` uses the same analysis-session bootstrap. Use `--cutoff` to set the canonical evidence cutoff. The value must fall within the indexed history — a cutoff before the earliest retrieved evidence returns zero rows. Check the earliest available `retrieved_at` first if you do not already know a cutoff that the data covers:

```sh
uv run epl-forecast data query --sql "SELECT min(retrieved_at) AS earliest FROM analysis.canonical"
uv run epl-forecast data query --cutoff <ISO-8601 timestamp> --sql 'SELECT season_id, count(*) AS matches FROM analysis.matches GROUP BY 1 ORDER BY 1'
```

The session reads the canonical manifest catalog from R2. Raw canonical and provider views remain available for expert use.

R2 is the only source of truth for an analysis session. `data query`, `data ui`, and the query skill helper keep the prepared `analysis` schema in one read-only DuckDB session file in the `page324-analysis` directory of the system temporary directory. The session file is a disposable copy. Nothing in the repository or in `runs/` holds analysis data.

Before each command opens a session file, it reads the canonical manifest catalog and the publication indexes from R2 again. The session file name is a hash of these documents, the evidence cutoff, `ANALYSIS_SCHEMA_VERSION`, the DuckDB version, and the `epl_forecast` package source. A change to one of these inputs selects a new file, and the command then prepares it from R2. Preparation reads all of the indexed history, so it takes much longer than a query on an existing file. The command deletes the earlier file for the same cutoff. The session file keeps canonical and derived tables and the views that use them. Before the command uses a new file, it opens the file with external access disabled and binds each object, so a view that reads R2 or a local file stops the preparation. You can delete the directory at any time.

The identity uses the mutable indexes only. Forecast, run, and hindcast artifacts are immutable at their keys. Do not replace an artifact in place: publish a new key and update its index.

### Analysis catalog

Start with the catalog:

```sql
SELECT object_name, grain, temporal_semantics, private, caveats
FROM analysis.catalog
ORDER BY object_name;
```

`analysis.session` records the analysis schema version, canonical evidence cutoff, manifest identity, loaded manifest batches, publication-index timestamps, and loaded public model versions. `analysis.column_catalog` describes every analysis column, including its DuckDB type, meaning, scale, null rule, and source field.

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

`analysis.forecast_matches` has the complete modeled match set from the private run. `on_public_surface` says whether the public forecast included that match in its short horizon. Its `structural_p_*` and `market_assisted_p_*` columns are compatibility columns. Use `analysis.forecast_match_stages` as the authoritative probability-stage relation.

The match stages are:

| Stage | Parent | Score-generating | Meaning |
| --- | --- | --- | --- |
| `unadjusted` | Model state | Yes | The model prediction before a match-specific personnel shift. |
| `personnel_adjusted` | `unadjusted` | Yes | The score distribution after the temporary personnel log-rate shift. A neutral or unusable adjustment leaves the distribution unchanged. |
| `market_assisted` | `personnel_adjusted` | No | The logarithmic pool with de-vigged market outcome probabilities. It has no goal rates or score grid. |

New private artifacts retain every stage. A historical private artifact retained only the post-personnel structural distribution. For such an artifact, `unadjusted` is available only when no nonzero personnel shift was applied. Otherwise, `available=false`, the probability and rate columns are null, and `availability_reason` explains why. The analysis layer does not reconstruct discarded probabilities.

`analysis.forecast_score_distributions` gives the goal rates, omitted tail, uncertainty components, and grid dimensions for the two score-generating stages. `analysis.forecast_score_grid` gives one probability for each retained home and away goal pair. `analysis.forecast_match_stage_comparison` puts the three H/D/A triplets, both rate pairs, `D_home`, `D_away`, κ, δ, and the personnel-applied flag on one row.

```sql
SELECT f.generated_at, m.match_id, m.on_public_surface,
       s.unadjusted_p_home, s.unadjusted_p_draw, s.unadjusted_p_away,
       s.personnel_adjusted_p_home, s.personnel_adjusted_p_draw, s.personnel_adjusted_p_away,
       s.market_assisted_p_home, s.market_assisted_p_draw, s.market_assisted_p_away
FROM analysis.forecast_matches m
JOIN analysis.forecasts f USING (forecast_id, competition_id, season_id)
JOIN analysis.forecast_match_stage_comparison s USING (forecast_id, competition_id, season_id, match_id)
WHERE f.competition_id = 'eng-premier-league'
ORDER BY f.generated_at DESC, m.match_date
LIMIT 100;
```

`analysis.forecast_personnel_teams` gives each team's discontinuity and shift status. `analysis.forecast_personnel_players` gives each player's recent weight, membership, availability, selection probability, expected missing weight, and resolved contribution to team discontinuity. Unknown players have no invented contribution; their weight remains in `unresolved_weight`. `analysis.forecast_personnel_evidence` expands the membership and availability evidence arrays. `analysis.forecast_personnel_reference_matches` expands the recent squad reference matches.

```sql
SELECT c.match_id, p.side, p.player_name, p.selection_probability,
       p.discontinuity_contribution, e.evidence_kind, e.ordinal, e.basis
FROM analysis.forecast_personnel_players p
LEFT JOIN analysis.forecast_personnel_evidence e
  USING (forecast_id, competition_id, season_id, match_id, team_id, side, player_id)
JOIN analysis.forecast_match_stage_comparison c
  USING (forecast_id, competition_id, season_id, match_id)
WHERE c.personnel_applied
ORDER BY c.match_id, p.side, p.discontinuity_contribution DESC NULLS LAST, e.evidence_kind, e.ordinal;
```

`analysis.forecast_market_inputs` gives the selected decimal odds, de-vigged probabilities, raw implied-probability sum, and pool weight. Join it to `forecast_match_stage_comparison` to inspect the input and output of the logarithmic pool.

`analysis.forecast_teams` and its event, distribution, and interval children contain the published and rounded product values. The `analysis.forecast_simulation_*` relations contain the raw private simulation output: run settings and diagnostics, team scalars, event probabilities, points, position and goal-difference distributions, intervals, conditional European probabilities, and match frequencies. The equivalent `analysis.hindcast_simulation_*` relations expose fields that each historical private hindcast actually retained. They do not fabricate removed historical fields.

`analysis.model_team_states` exposes Quality, its level and form, Tilt, their uncertainty and covariance, derived attack and defense state, state source, and match counts. It also keeps the complete state as JSON. `analysis.forecast_runs` exposes stable run-level model, rate, uncertainty, personnel, and market-assistance fields. `analysis.model_specifications` gives the mixture specification parameters, weights, and log evidence. Irregular fit diagnostics and provenance remain JSON.

`analysis.forecast_impact_fixtures` gives fixture-level sample, uncertainty, status, window, and carry-forward metadata. `analysis.forecast_impacts` is long-form by match, event, team, and outcome. For scheduled fixtures, its `baseline` is reconstructed from the published team event probability that the publication contract intentionally does not repeat.

### Hindcasts and timing

`analysis.hindcast_origins` and its child relations come only from `hindcasts/index.json` and the season series to which it points. Every origin has `retrospective=true`. `origin_at` is the simulated historical origin. It is not the time at which the artifact existed. `generated_at` is null by design.

The archive keeps every published model version. The index holds one season series for each model version, competition and season, and it does not remove a superseded version. `hindcast_id` is the origin timestamp alone, so the same `hindcast_id` occurs once for each model version. The identity of a hindcast row is therefore `hindcast_id`, `competition_id`, `season_id` and `model_version` together. Filter or group by `model_version` whenever you compare or total hindcast rows. Without it, a points or position distribution totals the number of published model versions, not 1.

```sql
SELECT model_version, count(*) AS origins
FROM analysis.hindcast_origins
GROUP BY 1 ORDER BY 1;
```

`analysis.team_projections` is a convenience union of live and hindcast team estimates. Its `model_version` is the public model version of each product. Do not replace its explicit time fields with one generic `as_of` value:

```sql
SELECT product, retrospective, model_version, generated_at, origin_at, state_observed_at,
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
