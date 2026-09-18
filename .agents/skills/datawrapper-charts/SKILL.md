---
name: datawrapper-charts
description: Create, edit, review, publish, or export Page 324 charts through the configured Datawrapper MCP server. Use for Datawrapper chart work in this repository.
---

# Datawrapper Charts

Treat each Datawrapper chart as output derived from a published Page 324 forecast. The sanitized publication bucket `page324-publish` is the source of truth. The files under `site/data/` are a generated copy and are not committed. A Datawrapper chart, its metadata, and its chart ID do not define the product contract.

## Use the MCP server

- Use the `datawrapper` MCP tools for chart operations.
- If the tools are absent, tell the user to restart their client after the MCP setup. The server must be registered for the client in use. Do not copy an API token into a prompt, tool argument, tracked file, or response.
- Use `list_chart_types` and `get_chart_schema` before you create a chart or make a material style change. The server is experimental, so inspect its current schema instead of relying on memory.
- Use `get_chart` before you edit an existing chart.

## Select data

- Read the publication contract in `docs/operations.md` ("Publication layout").
- Read the published values through the `query-football-data` skill. `analysis.forecast_teams` and its event, distribution and interval children hold the published and rounded product values. Do not materialize the site to a temporary directory.
- `analysis.forecast_matches` comes from the private run, so `structural_p_*` is not rounded. It equals the published `p_*` only after you round it to 6 decimal places, which is what `publication.probability` does.
- Start with `forecasts/current.json`. It has one latest pointer for each competition. Follow the `href` of the requested competition to `forecasts/<competition>/<forecast_id>.json`.
- For an earlier forecast, read `forecasts/<competition>/archive.json` and select the requested `forecast_id`. Use the latest forecast only when the user did not request another one.
- Do not use `forecasts/index.json`, forecast keys of the form `forecasts/<run>/<competition>.json`, or snapshot IDs. They are from the old layout and are not current.
- Do not use documents under `hindcasts/` as live forecasts.
- Read values from the selected forecast document. Do not copy values from a chart or from `configs/datawrapper_poc.toml`.
- Keep the forecast ID, the generated time, the public model version (`model.version`, for example `v0.0`), the competition, the event, and the units with the chart input.
- Use only the public model version on a chart. Do not use internal model names, such as the model IDs in `configs/product.toml`. The publication boundary does not permit them.
- Use `configs/datawrapper_poc.toml` only when the user explicitly asks to update the disposable smoke-test chart. Do not use that chart ID as a template or a required production ID.

## Refresh the defined chart set

`charts/definitions.toml` holds the defined set of charts and `scripts/refresh_charts.py` writes each one again from the latest published forecast. Read `charts/README.md` first.

- Use the refresh command for a chart that is already in the set. Do not repeat its work by hand.
- Add a new chart to the set only when it has a stable editorial purpose. Give it an entry in `definitions.toml` and, when the form is new, one extraction function and one recipe function.
- Keep the three layers apart: extraction reads the forecast, the recipe holds the chart settings, the definition holds the editorial text and the chart ID.
- The command publishes only with `--publish`, and it publishes every chart it refreshed. Use that option only when the user asks for publication.

## Create or edit a chart

1. Identify the chart question and the exact source fields. Ask only when a missing choice changes the meaning of the chart.
2. Prepare a small table with clear column names. Preserve all applicable clubs or matches unless the chart states a visible selection rule.
3. Create a draft or update the requested chart. Add a clear title and a short introduction. Every chart carries the same attribution: source name `Page 324`, byline `Page 324`, source URL `https://page324.substack.com/`. The notes carry the forecast time as `YYYY-MM-DD HH:MM UTC`, the public model version and the simulation count when applicable. Do not print the raw forecast ID on a chart; format the time from it.
4. If the user asks to see or review the rendered chart, export a PNG and inspect it. Check the title, labels, order, value format, notes, source, clipping, overlap, and chart size. Otherwise, do not export an image automatically.
5. Compare the uploaded data with the source document. Check row counts and relevant probability totals. For one-winner events, the displayed values must total 100% within the precision of the source. A full position distribution is a stronger check: every club row and every position column must each total 100%. Then read the rendered numbers, not only the totals. A number helper that strips trailing zeros turns 50 into 5, and only a look at the export finds it.
6. Publish only when the user asked for publication. After publication, confirm the public version through `get_chart` and return the chart ID, editor URL, public URL, and source forecast ID.

## What the tools do

These come from making the first four draft charts. Check them again if the server changes.

- The MCP server offers bar, line, area, arrow, column, multiple column, scatter and stacked bar. Its chart-type map has no table, and it rejects one at both `get_chart_schema` and `create_chart`. Datawrapper itself supports `tables`, so make a table through the HTTP API instead. Read the token from the ignored `.env` and never print it.
- For a table, get the option names from `GET /v3/visualizations/tables`, field `defaultMetadata`. They are not the names the MCP server uses.
- A table cell scale does work, but the column key is an object, not a boolean. Set `columns[<name>].heatmap` to `{"enabled": true}`; `true` on its own is stored and does nothing. The scale itself is `visualize.heatmap`, with `enabled`, `mode`, `rangeMin`, `rangeMax` and `colors` as `[{"color": ..., "position": 0}, {"color": ..., "position": 1}]`. `rangeMin` and `rangeMax` are strings. One scale serves every coloured column in the table, so all of those columns must hold the same unit.
- `columns[<name>].minWidth` does shorten a table column; `width` and `fixedWidth` do not, and neither does a per-column `style.fontSize`. A numeric column holds about 45 px at `minWidth` 8 with `compactMode` true. A twenty-position matrix therefore needs about 1040 px, not the 1440 px that the default column width needs.
- `mobileFallback` is on for every Page 324 table. At 320 px the table then stacks each row into its own block of `showOnMobile` columns, and the export does show it. With the fallback off, a table that is too wide clips its last columns rather than dropping them, and the count that fits is one less than it looks: a table showed five of the six columns that `showOnMobile` selected. Keep the mobile set small either way, because the stacked form repeats a label for every field of every row.
- An export at exactly `publish.embed-width` also takes `publish.embed-height` and crops the image. Review at a width that is not the stored embed width.
- A table cell breaks a line at an en dash, so an interval such as `67–91` wraps onto two lines in a narrow column. Put a word joiner (U+2060) on each side of the dash. A column `width` does not prevent the wrap.
- `firstColumnIsSticky` keeps the club name in view when a wide table scrolls sideways.
- A `%` number format appends the sign. It does not multiply by 100. Upload percentage points, not probabilities, then use a format such as `0.0%`. Confirm this on the first export of every new chart type.
- `sort-bars` decides the order of equal values on its own. Sort the rows during extraction, set `sort-bars` to false, and keep the uploaded order.
- On a stacked bar, a segment that is too narrow loses its value label, and nothing reports it. Set `block-labels` to true so the row label takes its own line and the bar keeps the full width. Check the result at 320 px.
- A stacked bar colours a column, never a cell. To mark one value in each row, give each series two columns, one for the marked state and one for the usual state, and leave the unused one empty. An empty cell draws no segment and no label. `color-category.excludeFromKey` is stored but a stacked bar ignores it, so turn the colour key off and put the order of the series in the introduction.
- `create_chart` takes `chart_type`, `data` and `chart_config` as three separate arguments. It rejects a single combined object.
- `export_chart_png` returns the image inline. It does not write a file. It crops to the requested height, so leave the height unset unless you want a crop.

## Probability checks

- Confirm whether the chart schema expects probabilities or percentage points. A `%` suffix does not necessarily multiply a value by 100.
- Serialize numeric values with decimal arithmetic or explicit rounding. Do not upload binary floating-point artifacts such as `0.3999999999`.
- Do not display a nonzero probability as `0%`. Use enough optional decimal places to show the smallest values that matter, or state a visible threshold.
- Do not add precision that is absent from the forecast source.

## Boundaries

- Use ASD-STE100 Simplified Technical English for public chart text.
- Do not link a chart to the source-code repository.
- Keep temporary exports and materialized copies outside the repository unless the user asks to retain them.
- Do not turn an exploratory chart into a general chart framework or an automatic publication step without a separate request.
- Do not delete a chart unless the user explicitly identifies it and asks for deletion.
