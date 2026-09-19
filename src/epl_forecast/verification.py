"""Check an authoritative typed forecast result against what the product promises.

The MVP contract is a list of things every archive must contain and every archive
must be internally consistent about: probabilities that are probabilities, a score
matrix that agrees with the match probabilities drawn from it, a season simulation
whose event masses equal the number of places the competition actually awards, the
rules and sanctions in force at the cutoff, a playoff bracket conditioned on the same
paths as the table, and enough provenance to say what was known when.

Every check reads only the typed result database. It fails loudly rather than reporting a score.
"""

import json
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from epl_forecast.competitions import competition as competition_info
from epl_forecast.data.rules import league_rules, reviewed_rules_evidence
from epl_forecast.datasets import timestamp
from epl_forecast.market import logarithmic_pool
from epl_forecast.personnel import MAX_UNRESOLVED
from epl_forecast.postseason import playoff_format
from epl_forecast.simulation import EVERY_TEAM

LONDON = ZoneInfo("Europe/London")


def places(competition: str, season: str) -> dict[str, int]:
    """How many clubs each season event must hold, from the season's rules."""
    rules = league_rules(competition, season)
    awarded = {"title_probability": 1, "relegation_probability": rules.relegated}
    if rules.promotes:
        awarded |= {
            "automatic_promotion_probability": rules.automatic_promotion,
            "playoff_promotion_probability": 1,
            "promotion_probability": rules.automatic_promotion + 1,
        }
    return awarded


class Checks:
    def __init__(self):
        self.results = []

    def check(self, name, condition, detail=""):
        self.results.append({"check": name, "passed": bool(condition), "detail": str(detail)})
        return bool(condition)

    @property
    def failures(self):
        return [r for r in self.results if not r["passed"]]


def verify_forecast(forecast: dict, run: dict) -> dict:
    checks = Checks()
    competition = forecast["competition_id"]
    season = forecast["season_id"]

    observed = timestamp(forecast["state_observed_at"])
    cutoff_day = date.fromisoformat(forecast["model_results_cutoff"])
    checks.check(
        "model cutoff is the London day of the observation",
        observed.astimezone(LONDON).date() == cutoff_day,
        f"{observed.isoformat()} -> {cutoff_day}",
    )
    checks.check(
        "generation follows observation",
        timestamp(forecast["generated_at"]) >= observed,
    )
    checks.check(
        "training stops before the cutoff day",
        date.fromisoformat(forecast["training_date_max"]) < cutoff_day,
        forecast["training_date_max"],
    )
    checks.check("provenance records the data manifest", bool(run.get("data_manifest")))
    checks.check("provenance records the model specification", bool(run.get("model")))
    checks.check("provenance records the seed and simulation count", "seed" in run)
    checks.check("source files are hashed", all(f.get("sha256") for f in forecast["sources"]))
    checks.check("no source errors", not forecast["source_errors"], forecast["source_errors"])

    upcoming = [m for m in forecast["matches"] if m.get("kickoff_time")]
    checks.check("the archive forecasts remaining fixtures", bool(upcoming), len(upcoming))
    for match in forecast["matches"]:
        probabilities = [match["p_home"], match["p_draw"], match["p_away"]]
        if not checks.check(
            f"match probabilities are a distribution: {match['match_id']}",
            all(0 <= p <= 1 for p in probabilities) and abs(sum(probabilities) - 1) < 1e-9,
            probabilities,
        ):
            break
        grid = np.asarray(match["score_distribution"]["grid_home_rows_away_columns"])
        omitted = match["score_distribution"]["omitted_probability"]
        if not checks.check(
            f"score matrix closes with its omitted tail: {match['match_id']}",
            abs(grid.sum() + omitted - 1) < 1e-9 and (grid >= 0).all() and omitted >= 0,
            f"{grid.sum():.9f} + {omitted:.9f}",
        ):
            break
        home = float(np.tril(grid, -1).sum())
        draw = float(np.trace(grid))
        away = float(np.triu(grid, 1).sum())
        if not checks.check(
            f"score matrix reproduces the outcome probabilities: {match['match_id']}",
            max(
                abs(home - match["p_home"]),
                abs(draw - match["p_draw"]),
                abs(away - match["p_away"]),
            )
            < omitted + 1e-9,
            f"grid {home:.5f}/{draw:.5f}/{away:.5f} vs {probabilities}",
        ):
            break
        if forecast.get("schema_version") != 2:
            continue
        stages = match.get("stages") or {}
        if not checks.check(
            f"all probability stages are explicit: {match['match_id']}",
            set(stages) == {"unadjusted", "personnel_adjusted", "market_assisted"},
            sorted(stages),
        ):
            break
        for stage_name in ("unadjusted", "personnel_adjusted"):
            stage = stages[stage_name]
            stage_probabilities = [stage[f"p_{side}"] for side in ("home", "draw", "away")]
            scores = stage["score_distribution"]
            stage_grid = np.asarray(scores["grid_home_rows_away_columns"])
            stage_tail = scores["omitted_probability"]
            stage_grid_probabilities = (
                float(np.tril(stage_grid, -1).sum()),
                float(np.trace(stage_grid)),
                float(np.triu(stage_grid, 1).sum()),
            )
            checks.check(
                f"{stage_name} probabilities are a distribution: {match['match_id']}",
                all(0 <= p <= 1 for p in stage_probabilities)
                and abs(sum(stage_probabilities) - 1) < 1e-9,
                stage_probabilities,
            )
            checks.check(
                f"{stage_name} score matrix closes: {match['match_id']}",
                abs(stage_grid.sum() + stage_tail - 1) < 1e-9
                and (stage_grid >= 0).all()
                and stage_tail >= 0,
            )
            checks.check(
                f"{stage_name} score matrix reproduces its outcomes: {match['match_id']}",
                max(
                    abs(grid_probability - probability)
                    for grid_probability, probability in zip(
                        stage_grid_probabilities, stage_probabilities, strict=True
                    )
                )
                < stage_tail + 1e-9,
            )
        original, adjusted = stages["unadjusted"], stages["personnel_adjusted"]
        record = match.get("personnel") or {}
        shift = record.get("home_log_rate_shift")
        expected_home_factor = np.exp(shift or 0)
        expected_away_factor = np.exp(-(shift or 0))
        checks.check(
            f"personnel stage applies the retained log-rate shift: {match['match_id']}",
            abs(
                adjusted["score_distribution"]["home_rate"]
                - original["score_distribution"]["home_rate"] * expected_home_factor
            )
            < 1e-10
            and abs(
                adjusted["score_distribution"]["away_rate"]
                - original["score_distribution"]["away_rate"] * expected_away_factor
            )
            < 1e-10,
            shift,
        )
        checks.check(
            f"legacy structural fields equal the personnel stage: {match['match_id']}",
            all(match[f"p_{side}"] == adjusted[f"p_{side}"] for side in ("home", "draw", "away")),
        )
        market = stages["market_assisted"]
        checks.check(
            f"market stage has no score distribution: {match['match_id']}",
            market is None or "score_distribution" not in market,
        )
        if market is not None:
            expected = logarithmic_pool(
                [adjusted[f"p_{side}"] for side in ("home", "draw", "away")],
                [market["market_probabilities"][f"p_{side}"] for side in ("home", "draw", "away")],
                market["market_weight"],
            )
            checks.check(
                f"market stage is the logarithmic pool: {match['match_id']}",
                max(
                    abs(market[f"p_{side}"] - probability)
                    for side, probability in zip(("home", "draw", "away"), expected, strict=True)
                )
                < 1e-12,
            )

    personnel = forecast.get("personnel")
    personnel_matches = [match for match in forecast["matches"] if match["personnel"] is not None]
    checks.check(
        "the personnel summary is retained when match personnel detail exists",
        not personnel_matches or personnel is not None,
        f"{len(personnel_matches)} detailed matches",
    )
    for match in forecast["matches"]:
        record = match["personnel"]
        if record is None or personnel is None:
            continue
        kickoff = timestamp(match["kickoff_time"])
        checks.check(
            f"personnel evidence is for a fixture within the horizon: {match['match_id']}",
            observed < kickoff <= observed + timedelta(days=personnel["horizon_days"]),
            f"{observed.isoformat()} -> {match['kickoff_time']}",
        )
        sheets = [record[side]["team_sheet_retrieved_at"] for side in ("home", "away")]
        checks.check(
            f"personnel team sheets were captured before the cutoff: {match['match_id']}",
            all(sheet is None or timestamp(sheet) <= observed for sheet in sheets),
            sheets,
        )
        shift = record["home_log_rate_shift"]
        if shift is None:
            continue
        home, away = record["home"], record["away"]
        checks.check(
            f"the personnel shift is kappa times the discontinuity difference: {match['match_id']}",
            abs(shift - personnel["kappa"] * (away["discontinuity"] - home["discontinuity"]))
            < 1e-12
            and max(home["unresolved_weight"], away["unresolved_weight"]) <= MAX_UNRESOLVED,
            shift,
        )

    unscheduled = [m for m in forecast["matches"] if m["status"] == "unscheduled"]
    checks.check(
        "postponed or undated fixtures are disclosed and placed on the cutoff day",
        sorted(m["match_id"] for m in unscheduled)
        == sorted(forecast.get("unscheduled_fixtures", []))
        and all(m["model_forecast_date"] == forecast["model_results_cutoff"] for m in unscheduled),
        [m["match_id"] for m in unscheduled],
    )

    unsettled = forecast.get("unsettled_fixtures", [])
    forecast_ids = {row["match_id"] for row in forecast["matches"]}
    checks.check(
        "a match that started without a result is disclosed and gets no match forecast",
        all(row["match_id"] not in forecast_ids for row in unsettled)
        and bool(forecast.get("unsettled_placeholder")) == bool(unsettled),
        [row["match_id"] for row in unsettled],
    )

    simulation = forecast["simulation"]
    if not checks.check(
        "a season projection is published",
        simulation is not None,
        forecast["simulation_unavailable_reason"],
    ):
        return {"checks": checks.results, "failures": len(checks.failures)}

    teams = simulation["teams"]
    expected_teams = competition_info(competition).teams
    checks.check("every club is projected", len(teams) == expected_teams, len(teams))
    for row in teams:
        points = row["points_distribution"]
        checks.check(
            f"points distribution closes: {row['team_id']}",
            abs(sum(points.values()) - 1) < 1e-9 and all(v >= 0 for v in points.values()),
        )
        positions = np.asarray(row["position_probabilities"])
        checks.check(
            f"rank distribution closes over every place: {row['team_id']}",
            len(positions) == expected_teams and abs(positions.sum() - 1) < 1e-9,
        )
        checks.check(
            f"reported intervals are present: {row['team_id']}",
            set(row["points_intervals"]) == {"50", "80", "90"}
            and set(row["position_intervals"]) == {"50", "80", "90"},
        )
    for event, awarded in places(competition, season).items():
        total = sum(row[event] for row in teams)
        checks.check(
            f"{event} mass equals the places awarded",
            abs(total - awarded) < 1e-6,
            f"{total:.6f} against {awarded}",
        )

    rules = league_rules(competition, season)
    checks.check(
        "the simulation used this season's ranking rules",
        simulation["ranking_rules"] == rules.ranking,
        simulation["ranking_rules"],
    )
    checks.check(
        "reviewed rules evidence is carried when it exists",
        simulation["ranking_rules_evidence"] == reviewed_rules_evidence(competition, season),
    )
    expected_adjustments = run.get("adjustments", [])
    applied = {(a["team_id"], a["points"]) for a in simulation["point_adjustments"]}
    checks.check(
        "sanctions in force at the cutoff are applied",
        applied == {(a["team_id"], a["points"]) for a in expected_adjustments},
        f"applied {sorted(applied)}",
    )

    if rules.promotes:
        model = simulation["playoff_model"]
        checks.check(
            "the bracket is conditioned on each path's own latent state",
            model["state_conditioning"].startswith("path-specific"),
            model["state_conditioning"],
        )
        checks.check(
            "the bracket is the season's reviewed edition",
            model["format"] == playoff_format(rules),
            model["format"],
        )
        checks.check(
            "promotion is automatic promotion plus the bracket",
            all(
                abs(
                    row["promotion_probability"]
                    - row["automatic_promotion_probability"]
                    - row["playoff_promotion_probability"]
                )
                < 1e-9
                for row in teams
            ),
        )

    impacts = simulation.get("match_impacts")
    if impacts:
        events = {
            (row["team_id"], event): value
            for row in teams
            for event, value in row.items()
            if event.endswith("_probability")
        }
        clubs = {row["team_id"] for row in teams}
        if impacts.get("window_start"):
            opening = timestamp(impacts["window_start"]).astimezone(LONDON)
            checks.check(
                "the impact window opens on the London day of the observation",
                opening.date() == observed.astimezone(LONDON).date()
                and (opening.hour, opening.minute, opening.second) == (0, 0, 0),
                impacts["window_start"],
            )
            checks.check(
                "the impact window closes at the horizon",
                timestamp(impacts["window_end"])
                == observed + timedelta(days=impacts["horizon_days"]),
                impacts["window_end"],
            )
        # Every club is measured against every fixture, so the rows are reported in
        # aggregate: one worst case for each fixture rather than one check for each row.
        for fixture in impacts["fixtures"]:
            counts = fixture["outcome_counts"]
            checks.check(
                f"conditional samples partition the paths: {fixture['match_id']}",
                sum(counts.values()) == simulation["simulations"],
                f"{sum(counts.values())} against {simulation['simulations']}",
            )
            sufficient = min(counts.values()) >= impacts["minimum_conditional_samples"]
            recovery_gap, published_gap, misreported, covered = 0.0, 0.0, 0, set()
            for row in fixture["impacts"]:
                recovered = sum(
                    counts[name] / simulation["simulations"] * row["conditional"][name]
                    for name in ("home", "draw", "away")
                    if counts[name]
                )
                recovery_gap = max(recovery_gap, abs(recovered - row["baseline"]))
                published_gap = max(
                    published_gap, abs(events[(row["team_id"], row["event"])] - row["baseline"])
                )
                misreported += row["sufficient_sample"] != sufficient
                covered.add(row["team_id"])
            rows = len(fixture["impacts"])
            checks.check(
                f"conditioning returns every club's season event in aggregate: {fixture['match_id']}",
                recovery_gap < 1e-6,
                f"largest gap {recovery_gap:.9f} over {rows} rows",
            )
            checks.check(
                f"every conditioned event is the published season event: {fixture['match_id']}",
                published_gap < 1e-6,
                f"largest gap {published_gap:.9f} over {rows} rows",
            )
            checks.check(
                f"every conditional reports its sample sufficiency: {fixture['match_id']}",
                not misreported,
                f"{misreported} rows against the smallest outcome sample {min(counts.values())}",
            )
            if impacts.get("coverage") == EVERY_TEAM:
                checks.check(
                    f"every club is measured against the fixture: {fixture['match_id']}",
                    covered == clubs,
                    f"{len(covered)} of {len(clubs)} clubs",
                )

    frequencies = {row["match_id"]: row for row in simulation["match_frequencies"]}
    published = {
        row["match_id"]: row for row in forecast["matches"] if row["match_id"] in frequencies
    }
    gaps = [
        (
            match_id,
            abs(frequencies[match_id]["p_home"] - published[match_id]["p_home"]),
            abs(frequencies[match_id]["p_draw"] - published[match_id]["p_draw"]),
        )
        for match_id in published
    ]
    worst = max((max(g[1], g[2]) for g in gaps), default=0.0)
    tolerance = 5 / np.sqrt(simulation["simulations"])
    checks.check(
        "simulated match frequencies agree with the published match model",
        worst < tolerance,
        f"largest gap {worst:.5f} against Monte Carlo tolerance {tolerance:.5f}",
    )
    return {
        "checks": checks.results,
        "failures": len(checks.failures),
        "matches_forecast": len(forecast["matches"]),
        "simulations": simulation["simulations"],
        "largest_frequency_gap": worst,
    }


def verify_result(database: Path, result_id: str) -> dict:
    from epl_forecast.results import read_forecast_result, read_forecast_run

    return verify_forecast(
        read_forecast_result(database, result_id),
        read_forecast_run(database, result_id),
    )


def verify_result_revision(
    database: Path,
    result_id: str,
    source_result_id: str,
    *,
    replace_market: bool,
    market_quotes: list[dict],
    market_pool: dict | None,
    team_names: dict[str, str] | None,
) -> dict:
    """Check a lightweight result against its structural source and replacement inputs."""
    import duckdb

    from epl_forecast.market import market_assisted_probabilities
    from epl_forecast.results import read_forecast_result, read_forecast_run

    checks = Checks()
    source = read_forecast_result(database, source_result_id)
    result = read_forecast_result(database, result_id)
    run = read_forecast_run(database, result_id)
    checks.check(
        "revision keeps the structural simulation", result["simulation"] == source["simulation"]
    )
    checks.check(
        "revision keeps the structural team strengths",
        result["team_strengths"] == source["team_strengths"],
    )
    source_matches = {row["match_id"]: row for row in source["matches"]}
    result_matches = {row["match_id"]: row for row in result["matches"]}
    checks.check(
        "revision keeps the structural match set",
        set(result_matches) == set(source_matches),
    )
    structural_fields = ("unadjusted", "personnel_adjusted")
    checks.check(
        "revision keeps every structural probability and score grid",
        all(
            result_matches[match_id]["stages"][stage] == source_match["stages"][stage]
            for match_id, source_match in source_matches.items()
            for stage in structural_fields
        ),
    )
    selected = {
        row["match_id"]: row
        for row in market_quotes
        if market_pool is not None and row["family"] == market_pool["market_family"]
    }
    market_matches = 0
    for match_id, match in result_matches.items():
        actual = match["market_assisted_probabilities"]
        if replace_market:
            quote = selected.get(match_id)
            expected = (
                None
                if quote is None
                else market_assisted_probabilities(
                    tuple(match[f"p_{side}"] for side in ("home", "draw", "away")),
                    quote,
                    market_pool,
                )
            )
        else:
            expected = source_matches[match_id]["market_assisted_probabilities"]
        if actual is not None:
            actual = {
                key: value
                for key, value in actual.items()
                if key not in {"parent_stage", "score_generating"}
            }
            market_matches += 1
        checks.check(f"revision market replacement is exact: {match_id}", actual == expected)
    assistance = result.get("market_assistance")
    checks.check(
        "revision refreshes aggregate market availability",
        (assistance is None and market_matches == 0)
        or (
            assistance is not None and assistance.get("available_match_forecasts") == market_matches
        ),
        market_matches,
    )
    checks.check(
        "revision applies the complete display replacement",
        team_names is None or result["team_names"] == team_names,
    )
    checks.check(
        "revision records its own requested cutoff",
        run.get("requested_cutoff") == result["state_observed_at"],
    )
    checks.check(
        "revision records current quote evidence",
        run.get("market_quote_evidence") == json.loads(json.dumps(market_quotes, default=str)),
    )
    with duckdb.connect(str(database), read_only=True) as connection:
        lineage = connection.execute(
            "SELECT source_result_id, market_replacement FROM forecast_result.forecast_runs "
            "WHERE result_id = ?",
            [result_id],
        ).fetchone()
        source_root = connection.execute(
            "WITH RECURSIVE lineage(result_id, source_result_id) AS ("
            "SELECT result_id, source_result_id FROM forecast_result.forecast_runs "
            "WHERE result_id = ? UNION ALL SELECT r.result_id, r.source_result_id "
            "FROM forecast_result.forecast_runs r JOIN lineage l "
            "ON r.result_id = l.source_result_id) "
            "SELECT result_id FROM lineage WHERE source_result_id IS NULL",
            [source_result_id],
        ).fetchone()
    checks.check(
        "revision has one structural lineage level",
        lineage == (source_root[0], True),
        lineage,
    )
    return {"checks": checks.results, "failures": len(checks.failures)}
