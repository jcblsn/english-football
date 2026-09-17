---
name: query-football-data
description: Query and analyze the repository's authoritative football data through its DuckDB analysis schema. Use for factual, exploratory, statistical, forecast, hindcast, personnel, and model-analysis questions that require repository data. Do not use local data files as historical evidence.
---

# Query Football Data

Use the authoritative remote corpus exposed in the `analysis` schema. Make the answer accurate and reproducible. Keep query output small enough to inspect.

## Frame the question

Before you query, identify the required population, grain, measure, comparison, and time meaning. Resolve a material ambiguity with a small discovery query when possible. Ask the user only when different reasonable choices would answer different questions.

Do not infer table or column semantics from names. Query the live catalog first:

```sh
.agents/skills/query-football-data/scripts/query --catalog 'probability stage'
.agents/skills/query-football-data/scripts/query --describe forecast_match_stages
```

Read the "Interactive analysis" section of `docs/data.md` only when you need maintained guidance about a relation, timing, or a join. Do not create a separate schema summary. Treat `analysis.catalog`, `analysis.column_catalog`, and `docs/data.md` as the contract.

## Query the data

Run SQL through the bounded query helper:

```sh
.agents/skills/query-football-data/scripts/query --sql 'SELECT competition_id, count(*) AS matches FROM analysis.matches GROUP BY 1 ORDER BY 1'
```

The helper keeps a disposable session file outside the repository and checks it against R2 on each call. The first call after R2 or the code changes prepares a new file from R2 and can take several minutes, so give that call a long command timeout. Later calls start in seconds. Do not read, change, or delete the session file directly.

Use `--sql-file <file>` for long SQL, or use `--sql-file -` to read SQL from stdin. Repeat `--query <name> <sql>` to run several named statements in one analysis session:

```sh
.agents/skills/query-football-data/scripts/query \
  --query coverage 'SELECT count(*) AS matches FROM analysis.matches' \
  --query competitions 'SELECT competition_id, count(*) AS matches FROM analysis.matches GROUP BY 1 ORDER BY 1'
```

Use `--cutoff <ISO-8601 timestamp>` when the question specifies an evidence cutoff. The cutoff meaning comes from the catalog and `docs/data.md`; do not apply one time field as a substitute for another.

Prefer curated `analysis.*` relations. Use raw canonical or provider views only when no curated relation answers the question and the source-level distinction is necessary.

Build focused queries:

- Select only the columns that answer the question. Do not use `SELECT *`.
- Filter early by competition, season, date, team, forecast, or origin when applicable.
- Aggregate in SQL. Return supporting totals and denominators with the requested statistic.
- Use explicit join keys that preserve the intended grain. Check `count(*)` against the relevant distinct key after a non-trivial join.
- Use a deterministic `ORDER BY` and a small `LIMIT` for detail rows.
- Do not alias a column to a DuckDB reserved word, such as `rows`, `first`, or `last` — the parser rejects it. Use a distinct name, such as `count_rows` or `first_day`.
- Inspect coverage, nulls, ranges, and category values with compact aggregate queries instead of printing sample tables.
- Keep unavailable evidence as unavailable. Do not replace null values, missing historical fields, or empty-response evidence with invented values.

For an unfamiliar question, use a short sequence: discover candidate relations, inspect only their columns, run one coverage or grain check, then run the analysis query. Combine independent checks in one SQL statement when that keeps the result clear.

## Protect context

The helper returns compact JSON and limits rows, long cells, and total output by default. It reports each type of truncation. It rounds floating-point output to six significant digits without changing SQL calculations. Use `--full-precision` only when the extra digits are necessary. Narrow the SQL before you increase a limit. Increase `--max-rows`, `--max-cell-chars`, or `--max-output-chars` only when the omitted detail is necessary for the answer.

Do not print large JSON columns. Extract the required keys with DuckDB JSON functions. Do not dump a full relation, a full catalog, or raw artifacts into context to discover their shape.

If analysis requires a large intermediate result, reduce it in SQL and return only the final table plus compact validation checks. Use the DuckDB UI for human-led exploration, not as a substitute for a reproducible agent query.

## Report the result

Lead with the answer. State the population, time basis, units, and important exclusions. Report sample size or denominator when it affects interpretation. Distinguish data facts from an inference. Mention material coverage limits, null handling, retrospective status, or truncation. Include the final SQL only when it helps the user reproduce or evaluate the result.
