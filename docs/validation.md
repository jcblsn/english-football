# Validation

Four kinds of evidence support M7. This page gives the results and the commands to reproduce them.

1. Product checks on every forecast archive.
2. Historical season panels in all four divisions.
3. A match scoreboard in the Premier League.
4. The prospective forecast record.

All historical forecasts on this page were made by code commit `fc94353` with the product configuration. The [evidence guide](../evidence/README.md) identifies the generated files in private R2 storage.

## Product checks

Every archive must pass the checks in the [product contract](mvp.md) before publication. A failed check stops the publication. These checks do not measure skill. They show that each forecast is internally consistent: probabilities, event totals, rules, sanctions, playoff conditioning and provenance.

## Season panels

Each panel forecasts complete historical seasons from five origins and scores the final table. M2 and M7 use the same fixtures, origins, seeds and 10,000 season paths. The tables show M7 − M2 with a season-clustered 95% interval. A negative difference is in favour of M7.

| Division | Seasons | Rank RPS lower for M7 | Rank RPS interval below zero | Event Brier intervals that favour M7 / M2 |
| --- | ---: | --- | --- | --- |
| Premier League | 11 | 4 of 5 origins | 0 of 5 origins | 3 / 0 of 20 |
| Championship | 11 | 5 of 5 origins | 3 of 5 origins | 4 / 0 of 25 |
| League One | 9 | 5 of 5 origins | 5 of 5 origins | 7 / 0 of 25 |
| League Two | 9 | 5 of 5 origins | 1 of 5 origins | 4 / 0 of 25 |

M7 is better than M2 in every division, but the size of the gain changes. The gain is largest where M2 has the least information: early in the season, and in the lower divisions. M2's 90% points intervals are too narrow early in the season in every division. M7's intervals are closer to 90%.

In the Premier League, no interval on rank RPS or points CRPS excludes zero. There, the evidence for M7 is the consistent direction, the better interval coverage and three event Brier scores. The Premier League result is weaker than the panel of 8 September 2026 on the research branch. That panel used an earlier M7 entry rule.

### Premier League

| Origin | Rank RPS M2 | Rank RPS M7 | M7 − M2 [95% interval] | Points CRPS M2 | Points CRPS M7 | M7 − M2 [95% interval] | 90% points coverage M2 / M7 |
| --- | ---: | ---: | --- | ---: | ---: | --- | ---: |
| preseason | 0.1105 | 0.1065 | −0.0040 [−0.0144, +0.0048] | 6.76 | 6.60 | −0.16 [−0.78, +0.36] | 73.6% / 81.8% |
| MW6 | 0.0946 | 0.0916 | −0.0030 [−0.0104, +0.0039] | 5.68 | 5.48 | −0.20 [−0.66, +0.20] | 74.5% / 82.7% |
| MW12 | 0.0781 | 0.0769 | −0.0012 [−0.0078, +0.0046] | 4.67 | 4.56 | −0.11 [−0.50, +0.24] | 80.0% / 86.8% |
| MW19 | 0.0589 | 0.0586 | −0.0003 [−0.0024, +0.0016] | 3.46 | 3.39 | −0.06 [−0.17, +0.04] | 86.4% / 90.0% |
| MW30 | 0.0412 | 0.0415 | +0.0004 [−0.0005, +0.0012] | 2.19 | 2.17 | −0.03 [−0.09, +0.03] | 90.0% / 91.4% |

### Championship

| Origin | Rank RPS M2 | Rank RPS M7 | M7 − M2 [95% interval] | Points CRPS M2 | Points CRPS M7 | M7 − M2 [95% interval] | 90% points coverage M2 / M7 |
| --- | ---: | ---: | --- | ---: | ---: | --- | ---: |
| preseason | 0.1632 | 0.1460 | −0.0172 [−0.0258, −0.0086] | 8.30 | 7.55 | −0.74 [−1.22, −0.24] | 73.1% / 86.4% |
| MW6 | 0.1415 | 0.1319 | −0.0096 [−0.0142, −0.0055] | 7.25 | 6.89 | −0.36 [−0.59, −0.12] | 74.2% / 86.7% |
| MW12 | 0.1238 | 0.1163 | −0.0075 [−0.0116, −0.0030] | 6.31 | 6.05 | −0.26 [−0.44, −0.07] | 76.9% / 86.0% |
| MW19 | 0.0991 | 0.0962 | −0.0029 [−0.0061, +0.0002] | 4.99 | 4.90 | −0.09 [−0.22, +0.06] | 81.1% / 87.9% |
| MW30 | 0.0634 | 0.0625 | −0.0009 [−0.0020, +0.0004] | 3.35 | 3.31 | −0.04 [−0.11, +0.03] | 84.8% / 88.3% |

### League One

| Origin | Rank RPS M2 | Rank RPS M7 | M7 − M2 [95% interval] | Points CRPS M2 | Points CRPS M7 | M7 − M2 [95% interval] | 90% points coverage M2 / M7 |
| --- | ---: | ---: | --- | ---: | ---: | --- | ---: |
| preseason | 0.1715 | 0.1518 | −0.0197 [−0.0312, −0.0087] | 9.46 | 8.49 | −0.96 [−1.55, −0.44] | 64.8% / 83.8% |
| MW6 | 0.1364 | 0.1255 | −0.0109 [−0.0167, −0.0042] | 7.49 | 7.13 | −0.36 [−0.75, +0.04] | 67.6% / 83.8% |
| MW12 | 0.1162 | 0.1084 | −0.0078 [−0.0116, −0.0043] | 6.62 | 6.25 | −0.37 [−0.61, −0.16] | 70.8% / 85.2% |
| MW19 | 0.0951 | 0.0910 | −0.0041 [−0.0075, −0.0006] | 5.21 | 5.13 | −0.08 [−0.26, +0.10] | 77.3% / 87.5% |
| MW30 | 0.0646 | 0.0623 | −0.0023 [−0.0043, −0.0007] | 3.49 | 3.44 | −0.05 [−0.12, +0.03] | 82.9% / 85.6% |

### League Two

| Origin | Rank RPS M2 | Rank RPS M7 | M7 − M2 [95% interval] | Points CRPS M2 | Points CRPS M7 | M7 − M2 [95% interval] | 90% points coverage M2 / M7 |
| --- | ---: | ---: | --- | ---: | ---: | --- | ---: |
| preseason | 0.1719 | 0.1609 | −0.0110 [−0.0261, +0.0035] | 8.03 | 7.58 | −0.46 [−0.95, +0.04] | 69.4% / 89.4% |
| MW6 | 0.1471 | 0.1348 | −0.0123 [−0.0186, −0.0052] | 6.91 | 6.44 | −0.48 [−0.76, −0.15] | 74.5% / 90.3% |
| MW12 | 0.1138 | 0.1089 | −0.0049 [−0.0121, +0.0018] | 5.48 | 5.24 | −0.24 [−0.51, +0.05] | 79.6% / 88.9% |
| MW19 | 0.0966 | 0.0942 | −0.0024 [−0.0056, +0.0009] | 4.73 | 4.61 | −0.13 [−0.29, +0.04] | 82.9% / 90.3% |
| MW30 | 0.0687 | 0.0679 | −0.0008 [−0.0026, +0.0009] | 3.42 | 3.38 | −0.04 [−0.15, +0.06] | 86.1% / 89.8% |

Each private `research/evidence/fc94353/season_panels/<division>/paired_comparisons.csv` object holds every comparison, including each event Brier score. Each `summary.csv` object holds the 50%, 80%, 90% and 95% coverage and width of the points and rank intervals.

## Match scoreboard

All forecasts below cover the same 1,140 Premier League matches in 2023/24–2025/26. Each model refits every day with earlier results only. Lower is better.

| Forecast | H/D/A log loss | Brier | Classwise ECE | Score NLL |
| --- | ---: | ---: | ---: | ---: |
| M2 | 0.98039 | 0.58378 | 0.02055 | 2.98251 |
| M7 | 0.97857 | 0.58167 | 0.03442 | 2.97278 |
| Average pre-closing market | 0.96502 | 0.57401 | 0.02037 | — |
| Average closing market | 0.95973 | 0.56989 | 0.01809 | — |

Over the full window, M7 has a lower log loss, Brier score and score NLL than M2. The gain is small: 0.0018 in log loss. M7 is not better in every season:

| Season | M2 log loss | M7 log loss | Pre-closing market log loss |
| --- | ---: | ---: | ---: |
| 2023/24 | 0.92936 | 0.93412 | 0.90925 |
| 2024/25 | 0.98533 | 0.97337 | 0.97055 |
| 2025/26 | 1.02649 | 1.02821 | 1.01525 |

The calibration error of M7 is higher than that of M2. Both models are worse than the betting market. For this reason, the market-assisted probability uses the market price with weight 1.0. See [methodology](methodology.md#market-assisted-probabilities).

Match scores are only a part of the case for M7. The difference between the models is larger in the season panels, because the state uncertainty of M7 matters most for season distributions.

## National League entry source

The National League is source evidence for the League Two entry prior. It is not a forecast competition. This change was compared with the exact main base `f3660fe` and uses the same M7 model except for the available source season.

The semantic checks show that a complete source season prevents an entrant from using the `outside` fallback. Withholding that season restores the fallback exactly. Future source results cannot affect an earlier forecast, and source matches do not update the League Two filter.

This is retrospective development evidence. On 180 first-10 entrant appearances in nine seasons, candidate minus control was −0.00296 H/D/A log loss, −0.00252 Brier and −0.00526 score NLL. Five of nine season effects favored the candidate on all three scores. On all 5,960 matched League Two matches, the changes were −0.00009 log loss, −0.00007 Brier and +0.00015 score NLL.

The matched 10,000-path season panel includes 16 source-conditioned entrant club-seasons in eight complete seasons. At preseason, candidate minus control was −0.00147 rank RPS and −0.175 points CRPS. The whole-season intervals include zero. Promotion Brier improved by 0.00442, relegation Brier worsened by 0.00082 and the 90% points interval became 0.44 points wider with unchanged coverage. Whole-League-Two effects were close to zero. The result supports the source-only correction, but the mixed season effects require prospective confirmation.

## Prospective record

`record.json` scores each published match forecast after the result. It uses the last live forecast made before kickoff. The record starts fresh with the production publication surface, so it has too few matches for a conclusion. It will become the main test of the product.

## Method

- Forecast origins: the first match day, and the day after the 6th, 12th, 19th and 30th nominal round. The rounds are proxies from match counts, not official rounds.
- Each origin fits the model from the start, with the results before the origin only. The simulation uses the recorded future schedule, not future results.
- Truth is the realized final table with every sanction in force at the end of the season. In the EFL divisions, the observed playoff winner is also truth.
- A forecast applies only the sanctions known at its origin.
- Rank RPS scores the whole position distribution. Points CRPS scores the whole points distribution. Coverage is the share of final totals inside the central interval.
- Each interval resamples whole seasons 10,000 times. The club-seasons in one season are not independent.
- This is retrospective evidence. The model specifications were developed with the same history. Results and xG are assumed available on the day after each match.

## Reproduce

Without provider data, download a private season panel to `runs/evidence/` and rescore it:

```sh
uv run python scripts/rescore_seasons.py --archive runs/evidence/eng-league-one/forecast_marginals.json.gz --output runs/rescore-league-one
uv run python scripts/report_seasons.py --evaluation runs/rescore-league-one --output runs/rescore-league-one/report
```

With access to `page324-data`, run a season panel again and archive it. The history comes from R2. The `--data` directory must be a new, empty workspace, not the repository `data/` directory:

```sh
OPENBLAS_NUM_THREADS=1 uv run python scripts/evaluate_seasons.py --data runs/workspace-panel --competition eng-league-one --models M2 M7 --seasons 2015 2016 2017 2018 2021 2022 2023 2024 2025 --output runs/panel-league-one
uv run python scripts/archive_seasons.py --data runs/workspace-panel --evaluation runs/panel-league-one --output runs/evidence/eng-league-one/forecast_marginals.json.gz
```

The Premier League and the Championship use the default seasons, 2015/16–2025/26. League One and League Two leave out 2019/20 and 2020/21, because the curtailed 2019/20 season has no complete table.

With access to `page324-data` and an empty workspace, run the match scoreboard and refit the market pool:

```sh
uv run epl-forecast evaluate --data runs/workspace-scoreboard --split validation --output runs/match-validation
uv run epl-forecast evaluate --data runs/workspace-scoreboard --split holdout --output runs/match-holdout
uv run python scripts/fit_market_pool.py --predictions <predictions> --markets <market predictions> --output runs/market-pool
```

For `fit_market_pool.py`, join the `predictions.csv` and `market_predictions.csv` files of the two splits. With the predictions of commit `fc94353`, the refit gives a weight of 1.0 over 1,140 matches. It reproduces `configs/market_pool.json` exactly.

The detailed studies behind the model choices are on the research branch. See [research history](research.md).
