# Evidence

This directory documents the evidence behind [validation](../docs/validation.md). Generated model output is in the private data bucket under `research/evidence/`, in the prefix that each row below names. Git contains the source, configuration, commands and reported results, but it does not contain generated evaluation files.

| Private R2 key | Content |
| --- | --- |
| `research/evidence/fc94353/match_scoreboard/predictions.csv.gz` | M2 and M7 H/D/A forecasts for 1,140 Premier League matches in 2023/24–2025/26, with outcomes and score log-likelihoods. |
| `research/evidence/fc94353/season_panels/<division>/forecast_marginals.json.gz` | The points and position distributions of every M2 and M7 season forecast, with the realized final tables. |
| `research/evidence/fc94353/season_panels/<division>/forecast_marginals.json.index.json` | The hash, seasons and forecast count of the archive. |
| `research/evidence/fc94353/season_panels/<division>/summary.csv` | Scores for each model and origin. |
| `research/evidence/fc94353/season_panels/<division>/paired_comparisons.csv` | M7 − M2 differences with season-clustered 95% intervals. |
| `research/evidence/national-league-entry/39bf554/match/` | Matched League Two control and source-conditioned match forecasts, scores, slices and input manifest. |
| `research/evidence/national-league-entry/28c0f5d/season-control/` | Matched goals-only M7 season forecasts with National League entrants treated as outside. |
| `research/evidence/national-league-entry/28c0f5d/season-candidate/` | Matched M7 season forecasts with complete National League source seasons available. |
| `research/evidence/national-league-entry/0729098/season-report/` | Paired entrant and whole-League-Two season results. |
| `research/evidence/api-football-xg/862a1c4/match-validation/` and `match-holdout/` | Premier League match scoreboard with API-Football xG. |
| `research/evidence/api-football-xg/862a1c4/market-pool/` | Market pool fitted again on the API-Football xG predictions. |
| `research/evidence/api-football-xg/862a1c4/season-panel-championship/` | Championship M7 season forecasts with API-Football xG, 2023/24–2025/26. |
| `research/evidence/api-football-xg/862a1c4/season-panel-premier-league/` and `f3660fe/season-panel-premier-league-before/` | Premier League M7 season forecasts with API-Football xG and with Understat xG, 2022/23–2025/26. |
| `research/evidence/championship-xg/77b685e/match/eng-championship/` | Championship goals-only and API-Football xG match forecasts; the `api-raw` arm is the product rule. |
| `research/evidence/m10-quality-dynamics/5a0893a/` | The M10 Quality dynamics runs of `v0.3.0`: the rolling candidate grid, the season panels, the match scoreboard, the market pool refit, the pre-merge checks, the production equivalence and the product checks. `manifest.json` lists each file with its size and SHA-256. |

Code commit `fc94353` made the forecasts under `research/evidence/fc94353/`, with the product configuration: the match scoreboard and the four season panels. The other rows name the commit that made them in their own key. The M10 runs were made at several commits of the research and release branches, so their key names the research commit that holds the memos, and each run records its own code state. The matchday-squad continuity evidence of `v0.2` is not in this table; it comes from the `research-personnel-measurement` branch under `research/evidence/personnel-measurement/`. See [validation](../docs/validation.md#matchday-squad-continuity).

An operator with private bucket access can download one marginal archive to `runs/evidence/`, then rescore it without provider data:

```sh
uv run python scripts/rescore_seasons.py --archive runs/evidence/eng-league-one/forecast_marginals.json.gz --output runs/rescore-league-one
uv run python scripts/report_seasons.py --evaluation runs/rescore-league-one --output runs/rescore-league-one/report
```

Do not edit archived evidence by hand. Replace it only with the output of a new, recorded evaluation.
