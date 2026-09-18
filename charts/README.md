# Charts

`definitions.toml` holds the defined set of Page 324 Datawrapper charts. `scripts/refresh_charts.py` reads it and writes each chart again from the latest published forecast.

The production process has three layers, and the code keeps them apart:

- Data extraction: a published forecast document becomes a small table. The extraction functions read the public forecast surface through the `analysis` schema.
- Chart recipe: the chart form, the order, the precision, the colours, the labels and the Datawrapper settings. One recipe function for each chart form.
- Editorial instance: the competition, the event, the title, the introduction and the chart ID. These are in `definitions.toml`.

A chart ID in `definitions.toml` identifies a draft Datawrapper chart. It is not part of the product contract. The forecast documents in `page324-publish` stay the source of truth.

## Refresh

```sh
uv run python scripts/refresh_charts.py                       # every chart, latest forecast
uv run python scripts/refresh_charts.py --chart iRGbS         # one chart
uv run python scripts/refresh_charts.py --forecast <id>       # an earlier forecast
uv run python scripts/refresh_charts.py --dry-run             # show the chart data, upload nothing
uv run python scripts/refresh_charts.py --export-dir <dir>    # write review PNGs
uv run python scripts/refresh_charts.py --publish             # publish after the refresh
```

Each refresh prints the forecast ID, the public model version, the simulation count and the checks. It then reads the uploaded data back and compares it with the extraction.

The command needs `DATAWRAPPER_API_KEY` in `.env`. It publishes only with `--publish`, and then it prints the public version and URL of each chart. Without that option it writes the draft and stops.

Keep review PNGs outside the repository.
