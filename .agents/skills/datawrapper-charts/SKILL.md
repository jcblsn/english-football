---
name: datawrapper-charts
description: Create, edit, review, publish, or export Page 324 charts through the configured Datawrapper MCP server. Use for Datawrapper chart work in this repository.
---

# Datawrapper Charts

Treat each Datawrapper chart as output derived from the forecast archive. The committed JSON under `site/data/` is the source of truth. A Datawrapper chart, its metadata, and its chart ID do not define the product contract.

## Use the MCP server

- Use the `datawrapper` MCP tools for chart operations.
- If the tools are absent, tell the user to restart Codex after the MCP setup. Do not copy an API token into a prompt, tool argument, tracked file, or response.
- Use `list_chart_types` and `get_chart_schema` before you create a chart or make a material style change. The server is experimental, so inspect its current schema instead of relying on memory.
- Use `get_chart` before you edit an existing chart.

## Select data

- Start with `site/data/index.json` and select the requested snapshot and competition. Use the newest available snapshot only when the user did not request another one.
- Read values from the selected published forecast document. Do not copy values from a chart or from `configs/datawrapper_poc.toml`.
- Keep the snapshot ID, generated date, model ID, competition, event, and units with the chart input.
- Use `configs/datawrapper_poc.toml` only when the user explicitly asks to update the disposable smoke-test chart. Do not use that chart ID as a template or a required production ID.

## Create or edit a chart

1. Identify the chart question and the exact source fields. Ask only when a missing choice changes the meaning of the chart.
2. Prepare a small table with clear column names. Preserve all applicable clubs or matches unless the chart states a visible selection rule.
3. Create a draft or update the requested chart. Add a clear title, a short introduction, Page 324 attribution, the forecast date, and the simulation count when applicable. Add a source URL only when a verified public Page 324 source page exists.
4. If the user asks to see or review the rendered chart, export a PNG and inspect it. Check the title, labels, order, value format, notes, source, clipping, overlap, and chart size. Otherwise, do not export an image automatically.
5. Compare the uploaded data with the source document. Check row counts and relevant probability totals. For one-winner events, the displayed values must total 100% within the precision of the source.
6. Publish only when the user asked for publication. After publication, confirm the public version through `get_chart` and return the chart ID, editor URL, public URL, and source snapshot ID.

## Probability checks

- Confirm whether the chart schema expects probabilities or percentage points. A `%` suffix does not necessarily multiply a value by 100.
- Serialize numeric values with decimal arithmetic or explicit rounding. Do not upload binary floating-point artifacts such as `0.3999999999`.
- Do not display a nonzero probability as `0%`. Use enough optional decimal places to show the smallest values that matter, or state a visible threshold.
- Do not add precision that is absent from the forecast source.

## Boundaries

- Use ASD-STE100 Simplified Technical English for public chart text.
- Do not link a chart to the source-code repository.
- Keep temporary exports outside the repository unless the user asks to retain them.
- Do not turn an exploratory chart into a general chart framework or an automatic publication step without a separate request.
- Do not delete a chart unless the user explicitly identifies it and asks for deletion.
