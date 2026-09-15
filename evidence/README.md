# Evidence

This directory documents the evidence behind [validation](../docs/validation.md). Generated model output is in the private data bucket under `research/evidence/fc94353/`. Git contains the source, configuration, commands and reported results, but it does not contain generated evaluation files.

| Private R2 key | Content |
| --- | --- |
| `research/evidence/fc94353/match_scoreboard/predictions.csv.gz` | M2 and M7 H/D/A forecasts for 1,140 Premier League matches in 2023/24–2025/26, with outcomes and score log-likelihoods. |
| `research/evidence/fc94353/season_panels/<division>/forecast_marginals.json.gz` | The points and position distributions of every M2 and M7 season forecast, with the realized final tables. |
| `research/evidence/fc94353/season_panels/<division>/forecast_marginals.json.index.json` | The hash, seasons and forecast count of the archive. |
| `research/evidence/fc94353/season_panels/<division>/summary.csv` | Scores for each model and origin. |
| `research/evidence/fc94353/season_panels/<division>/paired_comparisons.csv` | M7 − M2 differences with season-clustered 95% intervals. |

Code commit `fc94353` made all these forecasts, with the product configuration.

An operator with private bucket access can download one marginal archive to `runs/evidence/`, then rescore it without provider data:

```sh
uv run python scripts/rescore_seasons.py --archive runs/evidence/eng-league-one/forecast_marginals.json.gz --output runs/rescore-league-one
uv run python scripts/report_seasons.py --evaluation runs/rescore-league-one --output runs/rescore-league-one/report
```

Do not edit archived evidence by hand. Replace it only with the output of a new, recorded evaluation.
