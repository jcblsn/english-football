# Validation

Four kinds of evidence support M7. This page gives the results and the commands to reproduce them.

1. Product checks on every forecast archive.
2. Historical season panels in all four divisions.
3. A match scoreboard in the Premier League.
4. The prospective forecast record.

Each section names the code that produced its own evidence. Code commit `fc94353` made the season panels, the match scoreboard and the market pool fit that the first three sections report, with the product configuration. It did not make the evidence of the later sections: the National League entry source, API-Football xG and matchday-squad continuity each name the commits and runs behind them. The [evidence guide](../evidence/README.md) identifies the generated files in private R2 storage.

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

## API-Football xG

M7 uses API-Football team xG in every division from the first match with API-Football xG in that division. Before that date, the Premier League uses Understat xG. The xG enters the existing observation model unchanged. This change was compared with M7 before the change. All results are retrospective development evidence, and API-Football xG rows were captured after the seasons, so next-day availability is an assumption.

### Match forecasts

The Premier League scoreboard uses the same 1,140 matches in 2023/24–2025/26 as the table above.

| M7 | H/D/A log loss | Brier | Classwise ECE | Score NLL |
| --- | ---: | ---: | ---: | ---: |
| Understat xG | 0.97857 | 0.58167 | 0.03442 | 2.97278 |
| API-Football xG | 0.97830 | 0.58143 | 0.03205 | 2.96335 |

API-Football minus Understat is −0.00027 log loss, with a 95% paired 28-day block interval of [−0.00250, +0.00199]. By season, the log-loss change is +0.00003, −0.00258 and +0.00174. The change is neutral on H/D/A scores, and it improves score NLL and calibration.

In the Championship, M7 had no xG before this change. On 1,656 matches in 2023/24–2025/26, API-Football xG minus goals only is −0.00554 log loss [−0.00900, −0.00174], −0.00382 Brier and −0.01081 score NLL. Each of the three seasons improves on all three scores. Classwise ECE is 0.01408 before and 0.01446 after. The largest gain follows a match with a goal/xG gap of at least 1.5 (−0.01205 log loss), and the opening five fixtures of each club are slightly worse (+0.00122). These Championship forecasts come from the xG research run at commit `77b685e`. The product M7 of this change gives the same Championship match probabilities to within 3e-16.

League One and League Two have API-Football xG only from August 2026, so this change has no historical evaluation there.

### Season panels

Each panel compares M7 with API-Football xG with M7 before the change, on the same seasons, origins, schedules, seed 20260908, 10,000 paths and rules. Negative differences favour API-Football xG. With few seasons, the per-season effects are more informative than a resampled interval.

Championship, 72 club-seasons at each origin in 2023/24–2025/26. The M7 forecasts before the change come from the xG research panel at commit `4c38c5e`, which uses the product M7 of the main base.

| Origin | Rank RPS | Points CRPS | 90% points width | 80% points coverage | 90% points coverage |
| --- | ---: | ---: | ---: | --- | --- |
| preseason | −0.0057 | −0.23 | 39.35 → 38.35 | 81.9% → 80.6% | 87.5% → 87.5% |
| MW6 | −0.0058 | −0.15 | 35.03 → 33.40 | 80.6% → 75.0% | 88.9% → 86.1% |
| MW12 | −0.0082 | −0.35 | 30.65 → 28.94 | 79.2% → 75.0% | 88.9% → 95.8% |
| MW19 | −0.0012 | −0.07 | 25.78 → 24.36 | 80.6% → 79.2% | 91.7% → 93.1% |
| MW30 | −0.0028 | −0.14 | 18.10 → 17.47 | 81.9% → 76.4% | 84.7% → 87.5% |

Rank RPS and points CRPS improve at every origin. By season, rank RPS changes are 0.0000, +0.0065, +0.0004, −0.0002 and −0.0019 in 2023/24; −0.0122, −0.0087, −0.0097, −0.0078 and −0.0027 in 2024/25; and −0.0050, −0.0152, −0.0151, +0.0043 and −0.0038 in 2025/26. The 2023/24 MW6 forecast is worse because only a few weeks of xG were available. Title, automatic promotion, playoff and relegation Brier scores improve at every origin. Promotion Brier improves at four origins and is worse at MW30 (+0.0025). The intervals are narrower, and the 80% points coverage decreases at every origin.

Premier League, 80 club-seasons at each origin in 2022/23–2025/26. The M7 forecasts before the change come from the main base `f3660fe`.

| Origin | Rank RPS | Points CRPS | 90% points width | 80% points coverage | 90% points coverage |
| --- | ---: | ---: | ---: | --- | --- |
| preseason | +0.0007 | +0.01 | 32.38 → 32.38 | 72.5% → 72.5% | 81.2% → 81.2% |
| MW6 | +0.0008 | +0.04 | 27.91 → 27.75 | 72.5% → 70.0% | 77.5% → 78.7% |
| MW12 | +0.0008 | +0.05 | 23.93 → 23.95 | 75.0% → 72.5% | 86.2% → 86.2% |
| MW19 | +0.0003 | +0.00 | 19.40 → 19.43 | 81.2% → 80.0% | 91.2% → 91.2% |
| MW30 | +0.0000 | +0.01 | 11.79 → 11.89 | 85.0% → 81.2% | 92.5% → 91.2% |

In the Premier League, API-Football xG is slightly worse on season scores at every origin. The loss comes mostly from 2025/26, where rank RPS is +0.0048, +0.0053 and +0.0050 at preseason, MW6 and MW12. In 2023/24, rank RPS improves at the same origins (−0.0029, −0.0021, −0.0013), and 2024/25 is mixed. The 2022/23 forecasts are identical until MW19, because API-Football xG starts in January 2023. Title, top-four, top-five and relegation Brier changes are all smaller than 0.003.

### Production checks

At one cutoff on 15 September 2026, the forecast of each division passes every product check: 1,151 in the Premier League, 1,582 in the Championship, 1,602 in League One and 1,599 in League Two. The filters use 4,590, 1,721, 47 and 47 xG matches. Each derived public document has model version `v0.1` and passes the publication boundary.

The market pool was fitted again on the API-Football xG predictions of the 1,140 Premier League matches. It gives a market weight of 1.0 and reproduces `configs/market_pool.json` exactly, so the market-assisted probability does not change.

## Matchday-squad continuity

Model version v0.2 adds the matchday-squad continuity adjustment of the [methodology](methodology.md#matchday-squad-continuity). The owner decided on 15 September 2026 to release it on retrospective evidence. No prospective fixture was scored before the release. The research work is on the `research-personnel-measurement` branch, in `docs/experiments/personnel_measurement.md` and `docs/experiments/personnel_decision.md`.

Provenance: commit `fc94353` did not make any evidence in this section. The retrospective match scores, the coefficient κ and the q(m, n) table come from the runs of the `research-personnel-measurement` branch, archived under `research/evidence/personnel-measurement/` in `page324-data`. The production checks below come from the release branch of `v0.2` itself, at the cutoff they name.

### Retrospective match scores

The candidate adds the shift to the structural M7 forecast of the same match. The oracle uses the realized matchday squad after the match, so it measures the mechanism and is not a forecast. The history-only hindcast estimates D before each match day from earlier matchday squads and dated transfers. It uses no injury lists. Both use coefficients and q(m, n) tables from earlier seasons only. The scores cover 5,450 Premier League and Championship matches in 2020/21–2025/26. The values are candidate minus M7, and negative is better.

| Scope | Matches | Oracle score NLL | Hindcast H/D/A log loss | Hindcast Brier | Hindcast score NLL |
| --- | ---: | ---: | ---: | ---: | ---: |
| All | 5,450 | −0.00365 | −0.00126 | −0.00081 | −0.00152 |
| Premier League | 2,280 | −0.00497 | −0.00167 | −0.00102 | −0.00145 |
| Championship | 3,170 | −0.00271 | −0.00097 | −0.00065 | −0.00158 |
| Opening five matches | 577 | −0.00126 | −0.00048 | −0.00016 | −0.00116 |
| 2025/26 | 907 | −0.00261 | −0.00078 | −0.00039 | −0.00223 |
| Realized absolute D difference at least 0.20 | 403 | −0.03332 | −0.01025 | −0.00741 | −0.01677 |

With 12 competition-season clusters, the 95% interval of the hindcast score NLL difference is [−0.00232, −0.00077], and 11 of 12 cluster effects are below zero. The oracle interval is [−0.00509, −0.00244]. The hindcast keeps 42% of the oracle gain. The gain is concentrated: most of it comes from fixtures with a large difference between the clubs.

Both results are exposed to selection. The matchday-squad representation was chosen after a decomposition on the same seasons.

### Measurement at forecast horizons

In the development matches of 9–15 September 2026, before the release, the cutoff-safe estimator tracked the realized D_away − D_home with correlation 0.84 at 3 days (15 fixtures), 0.88 at 24 hours (20) and 0.92 at 90 minutes (23). No 6-day fixture was finished. These samples are too small for a forecast score.

### Production checks

At one cutoff on 15 September 2026, from an empty workspace against R2, the v0.2 forecast passes every product check: 1,181 in the Premier League and 1,599 in the Championship. The checks include the new personnel checks: each record is for a fixture in the next six days, each team sheet was captured before the cutoff, and each shift is κ(D_away − D_home) with both clubs within the unresolved limit.

- Premier League: all 10 fixtures in the horizon have a shift, from −0.054 to +0.081. Availability came from FPL, because API-Football had not yet published the injury lists of the next round.
- Championship: 9 of 12 fixtures in the horizon have a shift, from −0.068 to +0.032. Bolton Wanderers, Cardiff City and Lincoln City have fewer than eight previous matches with complete lineup minutes, so their fixtures have no shift. The largest unresolved weight of a club is 0.092.

The checks ran again from the released `main`, at commit `659f475`, whose forecast code is unchanged at `5b8bc96`. From an empty workspace against R2, at one cutoff on 16 September 2026 UTC, every division passes every check: 1,181 in the Premier League, 1,599 in the Championship, 1,602 in League One and 1,599 in League Two.

The personnel counts reproduce the release record. 10 of 10 Premier League fixtures in the horizon get a shift, and 9 of 12 in the Championship. League One and League Two hold no personnel record and no adjusted fixture, and their check counts equal the `v0.1` counts above, so the two divisions without the adjustment are unchanged.

The shift ranges are not the same: −0.065 to +0.0745 in the Premier League against −0.054 to +0.081, and −0.0624 to +0.0318 in the Championship against −0.068 to +0.032. The canonical history held no source snapshots at this pre-migration cutoff, so no injury list and no FPL status was readable, and the estimate rested on matchday squads and dated transfers. This is a dated release observation, not the current canonical-data contract. A shift range describes the evidence at one cutoff. It is not a fixed property of the model.

What the injury lists covered at the release is an observation of that moment, not a standing property of the provider. At 21:30 UTC on 15 September 2026, the latest API-Football injury capture covered fixtures up to that day and none of the next round. An adjustment several days before kickoff therefore rested on membership and FPL status, and in the Championship on membership alone.

The final canonical migration on 16 September 2026 replayed 8,281 retained request records with the released normalizers and made no provider request. Canonical compaction batch `1945bec7b268a7fc649b7073ed6f9eb89e1b6cd67bccc3d9397737ca80daa4c3` holds 24,268 distinct source-snapshot observations. These include 18 successful empty injury snapshots, 8 successful empty fixture-detail snapshots, 590 successful empty player-sidelined snapshots and 173 successful empty player-transfer snapshots. The compaction result had one manifest and 14 files, and its distinct row counts equal the union before compaction. The final production collection then added five incremental manifests from four fresh fixture-list responses.

The final clean-workspace production run used commit `0a65902370e89bcc5b05e11580ee1fa0e6813425`, model version `v0.2`, cutoff `2026-09-16T03:05:25.586801Z` and run ID `2026-09-16T030525Z`. It made four API-Football fixture-list requests, finished in 307 seconds and published all four divisions without a failure. The private archives record a clean worktree and this exact commit. The Premier League has 10 personnel records and 10 applied shifts; the Championship has 12 records and 9 applied shifts; League One and League Two have no personnel record or shift. Every archive states that the temporary adjustment did not change the persistent state and that market assistance did not enter the season simulation. The check counts are 1,181, 1,599, 1,602 and 1,599 in division order.

GitHub production workflow run `35050871557` then checked the same commit and compacted data on a hosted runner. It completed in 72 seconds with no provider request and no pending forecast, which confirms that the published fingerprints match the released code and data. Pages workflow run `35050829333` materialized and deployed the full publication surface from the same commit.

### The v0.2 hindcast archive

The `v0.2` hindcast archive is generated from the released `main` with the Wednesday origin protocol of [operations](operations.md#the-origin-protocol). It does not reuse the pre-release research hindcasts.

The immutable edition remains attributed to commit `79d5e8d`. Later release commits contain canonical-data and deterministic-selection corrections. They do not overwrite or relabel that edition.

| Item | Value |
| --- | --- |
| Released commit | `79d5e8d` |
| Generation | Workflow run `hindcast` 35040760653 made 104 origins; a local run of the same released code made the other 719 |
| Public model version | `v0.2` |
| Edition digest | `7c157a450abae14b052456f891df01ea05432597d42f557c29ac6f3c5e858577` |
| Origin protocol | Each Wednesday at 09:00 Europe/London |
| Seed and paths | 20260905, 10,000 |
| Scope | Four divisions, 2021/22–2025/26 |

The edition digest is the SHA-256 of the edition manifest that the run claims, over the model code hashes, the seed, the number of paths and the origin protocol. The same digest comes from the released commit on any machine, so a later reader can check that the archive was made by this code and this protocol:

```sh
uv run python -c "
from epl_forecast.hindcast import edition
from epl_forecast.publication import load_policy
from epl_forecast.storage import json_bytes, sha256_bytes
print(sha256_bytes(json_bytes(edition(load_policy()['product']['model_version'], 10000))))"
```

Both runs claimed the same edition. `claim_edition` compares the whole edition manifest and stops a run that does not match, so one archive cannot hold two models or two origin protocols.

The archive holds 823 weekly documents in 20 season series, one series for each division and season. Every origin falls on a Wednesday at 09:00 Europe/London, every weekly document that a series lists exists, and every per-club array holds one value for each origin.

| Division | Origins | Fixtures with an adjustment | Origins with at least one |
| --- | ---: | ---: | ---: |
| Premier League | 212 | 1,803 | 174 |
| Championship | 204 | 2,287 | 173 |
| League One | 203 | 0 | 0 |
| League Two | 204 | 0 | 0 |

League One and League Two hold no adjusted fixture at any origin. That is the unchanged behaviour of the two divisions that the adjustment does not cover.

The whole publication surface materializes and passes the boundary: 1,695 documents, which are the 823 `v0.2` and 825 `v0.0` weekly hindcasts, their 40 season series, the hindcast index, the current pointer, four forecasts and the record.

```sh
uv run epl-forecast materialize --site site --hindcasts
uv run python scripts/check_publishable.py --site site
```

### Prospective evaluation

The research branch archives the same estimator at 6 days, 3 days, 24 hours and 90 minutes before each Premier League and Championship fixture from 17 September 2026, with the structural M7 control and the realized-squad oracle. It evaluates measurement first and forecast scores by match round. The evidence is in `research/evidence/personnel-measurement/` in `page324-data`.

The monitoring population is frozen to Premier League and Championship regular-season fixtures in 2026/27 that kick off from 17 September 2026 00:00 UTC. The archive uses research freeze commit `6fc7d818bc08f2c8fec0c836bdc87eb817dc1285`. It does not refit κ, the matchday-squad propensity table, the availability values or the unresolved limit.

The first review is after the matches of 26 October 2026. The second review is after the matches of 30 November 2026. Remove the adjustment at a review when either condition is true on the prospective fixtures:

- At 24 hours, the correlation between estimated and realized D_away − D_home is below 0.5, or the sign agrees in less than 70% of fixtures whose realized absolute difference is at least 0.10.
- At 90 minutes, the whole-round 95% interval of candidate minus control score NLL is entirely above zero.

Remove or correct the adjustment at once if an audit finds a semantic or data error, such as a wrong club, a truncated squad, an identity split or an observation retrieved after the cutoff. A review that meets no removal condition keeps the adjustment without changing its frozen values.

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
