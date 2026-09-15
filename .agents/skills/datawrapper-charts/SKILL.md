---
name: datawrapper-charts
description: Create, edit, review, publish, or export Page 324 charts through the configured Datawrapper MCP server. Use for Datawrapper chart work in this repository.
---

# Datawrapper Charts

Treat each Datawrapper chart as output derived from a published Page 324 forecast. The sanitized publication bucket `page324-publish` is the source of truth. The files under `site/data/` are a generated copy and are not committed. A Datawrapper chart, its metadata, and its chart ID do not define the product contract.

## Use the MCP server

- Use the `datawrapper` MCP tools for chart operations.
- If the tools are absent, tell the user to restart Codex after the MCP setup. Do not copy an API token into a prompt, tool argument, tracked file, or response.
- Use `list_chart_types` and `get_chart_schema` before you create a chart or make a material style change. The server is experimental, so inspect its current schema instead of relying on memory.
- Use `get_chart` before you edit an existing chart.

## Select data

- Read the publication contract in `docs/operations.md` ("Publication layout").
- Get the documents from `page324-publish` with the `R2_PUBLISH_BUCKET` settings, or run `uv run epl-forecast materialize --site <temporary directory>` and read the local copy under `<temporary directory>/data/`. Add `--archive <competition>` to get an earlier forecast.
- Start with `forecasts/current.json`. It has one latest pointer for each competition. Follow the `href` of the requested competition to `forecasts/<competition>/<forecast_id>.json`.
- For an earlier forecast, read `forecasts/<competition>/archive.json` and select the requested `forecast_id`. Use the latest forecast only when the user did not request another one.
- Do not use `forecasts/index.json`, forecast keys of the form `forecasts/<run>/<competition>.json`, or snapshot IDs. They are from the old layout and are not current.
- Do not use documents under `hindcasts/` as live forecasts.
- Read values from the selected forecast document. Do not copy values from a chart or from `configs/datawrapper_poc.toml`.
- Keep the forecast ID, the generated time, the public model version (`model.version`, for example `v0.0`), the competition, the event, and the units with the chart input.
- Use only the public model version on a chart. Do not use internal model names, such as the model IDs in `configs/product.toml`. The publication boundary does not permit them.
- Use `configs/datawrapper_poc.toml` only when the user explicitly asks to update the disposable smoke-test chart. Do not use that chart ID as a template or a required production ID.

## Create or edit a chart

1. Identify the chart question and the exact source fields. Ask only when a missing choice changes the meaning of the chart.
2. Prepare a small table with clear column names. Preserve all applicable clubs or matches unless the chart states a visible selection rule.
3. Create a draft or update the requested chart. Add a clear title, a short introduction, Page 324 attribution, the forecast date, the public model version, and the simulation count when applicable. Add a source URL only when a verified public Page 324 source page exists.
4. If the user asks to see or review the rendered chart, export a PNG and inspect it. Check the title, labels, order, value format, notes, source, clipping, overlap, and chart size. Otherwise, do not export an image automatically.
5. Compare the uploaded data with the source document. Check row counts and relevant probability totals. For one-winner events, the displayed values must total 100% within the precision of the source.
6. Publish only when the user asked for publication. After publication, confirm the public version through `get_chart` and return the chart ID, editor URL, public URL, and source forecast ID.

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
