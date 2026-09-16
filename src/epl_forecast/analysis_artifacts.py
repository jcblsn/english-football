"""Normalize indexed publication artifacts into the DuckDB analysis schema."""

import json
from collections.abc import Iterable

from epl_forecast.competitions import COMPETITION_IDS


def _json(value) -> str | None:
    return None if value is None else json.dumps(value, sort_keys=True, allow_nan=False)


def _create_table(connection, name: str, columns: tuple[tuple[str, str], ...], rows=()) -> None:
    connection.execute(
        f"CREATE TABLE analysis.{name} ("
        + ", ".join(f'"{column}" {kind}' for column, kind in columns)
        + ")"
    )
    names = [column for column, _ in columns]
    values = [tuple(row.get(column) for column in names) for row in rows]
    if values:
        connection.executemany(
            f"INSERT INTO analysis.{name} VALUES ({', '.join('?' for _ in names)})", values
        )


def _document(store, key: str, version: int, kind: str) -> dict:
    document = store.get_json(key)
    if document is None:
        raise ValueError(f"The {kind} pointer does not resolve: {key}")
    if document.get("schema_version") != version:
        raise ValueError(f"Unsupported {kind} schema at {key}: {document.get('schema_version')!r}")
    return document


def _required(document: dict, fields: Iterable[str], kind: str) -> None:
    missing = sorted(set(fields) - set(document))
    if missing:
        raise ValueError(f"Missing {kind} fields: {', '.join(missing)}")


def _team_rows(product_id: str, team: dict, base: dict, targets: dict[str, list]) -> None:
    scalar = {
        **base,
        "team_id": team["team_id"],
        "team_name": team.get("name"),
        "played": team.get("played"),
        "current_points": team.get("current_points"),
        "mean_points": team.get("mean_points"),
        "median_points": team.get("median_points"),
        "mean_position": team.get("mean_position"),
        "median_position": team.get("median_position"),
        "position_sd": team.get("position_sd"),
        "mean_goal_difference": team.get("mean_goal_difference"),
    }
    targets[product_id + "_teams"].append(scalar)
    for event, probability in team.get("events", {}).items():
        targets[product_id + "_team_events"].append(
            {**base, "team_id": team["team_id"], "event": event, "probability": probability}
        )
    for points, probability in team.get("points_distribution", {}).items():
        targets[product_id + "_points_distribution"].append(
            {
                **base,
                "team_id": team["team_id"],
                "points": int(points),
                "probability": probability,
            }
        )
    for position, probability in enumerate(team.get("position_probabilities", ()), 1):
        targets[product_id + "_position_distribution"].append(
            {
                **base,
                "team_id": team["team_id"],
                "position": position,
                "probability": probability,
            }
        )
    for kind in ("points", "position"):
        for level, bounds in team.get(f"{kind}_intervals", {}).items():
            targets[product_id + "_intervals"].append(
                {
                    **base,
                    "team_id": team["team_id"],
                    "estimate": kind,
                    "level": int(level),
                    "lower": bounds[0],
                    "upper": bounds[1],
                }
            )


def _live_rows(data_store, publish_store) -> tuple[dict[str, list], dict, set[str]]:
    rows = {
        name: []
        for name in (
            "forecasts",
            "forecast_matches",
            "forecast_teams",
            "forecast_team_events",
            "forecast_points_distribution",
            "forecast_position_distribution",
            "forecast_intervals",
            "model_team_states",
            "forecast_runs",
            "forecast_impacts",
        )
    }
    updated = {}
    model_versions = set()
    for competition_id in COMPETITION_IDS:
        key = f"forecasts/{competition_id}/archive.json"
        archive = publish_store.get_json(key)
        if archive is None:
            continue
        if archive.get("schema_version") != 1:
            raise ValueError(
                f"Unsupported forecast archive schema at {key}: {archive.get('schema_version')!r}"
            )
        _required(archive, ("forecasts", "updated_at", "competition_id"), "forecast archive")
        if archive["competition_id"] != competition_id:
            raise ValueError(f"Forecast archive competition does not match its key: {key}")
        updated[key] = archive["updated_at"]
        for pointer in archive["forecasts"]:
            _required(pointer, ("forecast_id", "href"), "forecast pointer")
            public = _document(publish_store, pointer["href"], 3, "forecast")
            _required(
                public,
                (
                    "forecast_id",
                    "competition_id",
                    "season_id",
                    "generated_at",
                    "state_observed_at",
                    "model_results_cutoff",
                    "simulations",
                    "model",
                    "matches",
                    "teams",
                ),
                "forecast",
            )
            if public["forecast_id"] != pointer["forecast_id"]:
                raise ValueError(f"Forecast pointer identity does not match: {pointer['href']}")
            forecast_id = public["forecast_id"]
            private_prefix = f"runs/forecasts/{forecast_id}/{competition_id}"
            private = _document(
                data_store, f"{private_prefix}/forecast.json", 1, "private forecast"
            )
            run = data_store.get_json(f"{private_prefix}/run.json")
            if run is None:
                raise ValueError(
                    f"A successful public forecast has no private run: {private_prefix}"
                )
            if (
                private.get("competition_id") != competition_id
                or private.get("season_id") != public["season_id"]
            ):
                raise ValueError(f"Private and public forecast identities differ: {forecast_id}")
            public_matches = {match["match_id"] for match in public["matches"]}
            private_matches = {match["match_id"] for match in private.get("matches", ())}
            if not public_matches <= private_matches:
                raise ValueError(
                    f"Public forecast has matches absent from its private run: {forecast_id}"
                )
            model_version = public["model"]["version"]
            model_versions.add(model_version)
            base = {
                "forecast_id": forecast_id,
                "competition_id": competition_id,
                "season_id": public["season_id"],
            }
            rows["forecasts"].append(
                {
                    **base,
                    "generated_at": public["generated_at"],
                    "state_observed_at": public["state_observed_at"],
                    "model_results_cutoff": public["model_results_cutoff"],
                    "public_model_version": model_version,
                    "private_model_id": private.get("model", {}).get("id"),
                    "simulations": public["simulations"],
                    "public_href": pointer["href"],
                    "private_prefix": private_prefix,
                }
            )
            for match in private.get("matches", ()):
                assisted = match.get("market_assisted_probabilities")
                rows["forecast_matches"].append(
                    {
                        **base,
                        "match_id": match["match_id"],
                        "kickoff_time": match.get("kickoff_time"),
                        "match_date": match.get("match_date"),
                        "home_team_id": match["home_team_id"],
                        "away_team_id": match["away_team_id"],
                        "status": match.get("status"),
                        "on_public_surface": match["match_id"] in public_matches,
                        "structural_p_home": match.get("p_home"),
                        "structural_p_draw": match.get("p_draw"),
                        "structural_p_away": match.get("p_away"),
                        "market_assisted_p_home": None
                        if assisted is None
                        else assisted.get("p_home"),
                        "market_assisted_p_draw": None
                        if assisted is None
                        else assisted.get("p_draw"),
                        "market_assisted_p_away": None
                        if assisted is None
                        else assisted.get("p_away"),
                        "market_family": None
                        if assisted is None
                        else assisted.get("market_family"),
                        "market_observed_at": None
                        if assisted is None
                        else assisted.get("market_observed_at"),
                        "personnel": _json(match.get("personnel")),
                        "score_distribution": _json(match.get("score_distribution")),
                    }
                )
            simulation = private.get("simulation") or {}
            for team in simulation.get("teams", ()):
                public_team = next(
                    (row for row in public["teams"] if row["team_id"] == team["team_id"]), team
                )
                _team_rows("forecast", public_team, base, rows)
            for state in private.get("team_strengths", ()):
                rows["model_team_states"].append(
                    {
                        **base,
                        "team_id": state["team_id"],
                        "quality": state.get("quality"),
                        "attack_log_rate": state.get("attack_log_rate"),
                        "defense_log_rate": state.get("defense_log_rate"),
                        "attack_multiplier": state.get("attack_multiplier"),
                        "defense_multiplier": state.get("defense_multiplier"),
                        "training_matches": state.get("training_matches"),
                        "state": _json(state),
                    }
                )
            rows["forecast_runs"].append(
                {
                    **base,
                    "generated_at": public["generated_at"],
                    "model_id": private.get("model", {}).get("id"),
                    "package_version": run.get("package_version"),
                    "code_sha256": run.get("code_sha256"),
                    "commit": run.get("execution", {}).get("commit"),
                    "training_matches": private.get("training_matches"),
                    "fit_diagnostics": _json(private.get("fit_diagnostics")),
                    "provenance": _json(run),
                }
            )
            impact = public.get("impact") or {}
            for fixture in impact.get("fixtures", ()):
                carried = fixture.get("carried_from") or {}
                for event, block in fixture.get("impacts", {}).items():
                    for index, team_id in enumerate(block.get("team_id", ())):
                        for outcome in ("home", "draw", "away"):
                            values = block.get(outcome, ())
                            baselines = block.get("baseline", ())
                            movements = block.get("rms_movement", ())
                            rows["forecast_impacts"].append(
                                {
                                    **base,
                                    "match_id": fixture["match_id"],
                                    "event": event,
                                    "team_id": team_id,
                                    "outcome": outcome,
                                    "baseline": baselines[index]
                                    if index < len(baselines)
                                    else None,
                                    "conditional_probability": values[index]
                                    if index < len(values)
                                    else None,
                                    "rms_movement": movements[index]
                                    if index < len(movements)
                                    else None,
                                    "carried_from_forecast_id": carried.get("forecast_id"),
                                    "carried_from_generated_at": carried.get("generated_at"),
                                }
                            )
    return rows, updated, model_versions


def _hindcast_rows(data_store, publish_store) -> tuple[dict[str, list], dict, set[str]]:
    names = (
        "hindcast_origins",
        "hindcast_teams",
        "hindcast_team_events",
        "hindcast_points_distribution",
        "hindcast_position_distribution",
        "hindcast_intervals",
    )
    rows = {name: [] for name in names}
    index = publish_store.get_json("hindcasts/index.json")
    if index is None:
        return rows, {}, set()
    if index.get("schema_version") != 1 or index.get("retrospective") is not True:
        raise ValueError("Unsupported or non-retrospective hindcast index")
    _required(index, ("updated_at", "seasons"), "hindcast index")
    versions = set()
    for pointer in index["seasons"]:
        series = _document(publish_store, pointer["href"], 1, "hindcast series")
        if series.get("retrospective") is not True:
            raise ValueError(f"Hindcast series is not retrospective: {pointer['href']}")
        for origin in series["origins"]:
            public = _document(publish_store, origin["href"], 1, "hindcast")
            if public.get("retrospective") is not True:
                raise ValueError(f"Hindcast origin is not retrospective: {origin['href']}")
            private_key = f"runs/{origin['href']}"
            private = _document(data_store, private_key, 1, "private hindcast")
            if private.get("hindcast_id") != public.get("hindcast_id"):
                raise ValueError(f"Private and public hindcast identities differ: {origin['href']}")
            model_version = public["model"]["version"]
            versions.add(model_version)
            base = {
                "hindcast_id": public["hindcast_id"],
                "competition_id": public["competition_id"],
                "season_id": public["season_id"],
                "origin_at": public["origin_at"],
            }
            rows["hindcast_origins"].append(
                {
                    **base,
                    "retrospective": True,
                    "generated_at": None,
                    "model_results_cutoff": public["model_results_cutoff"],
                    "model_version": model_version,
                    "simulations": public["simulations"],
                    "played_matches": public.get("played_matches"),
                    "remaining_matches": public.get("remaining_matches"),
                    "public_href": origin["href"],
                    "private_key": private_key,
                }
            )
            for team in public["teams"]:
                _team_rows("hindcast", team, base, rows)
    return rows, {"hindcasts/index.json": index["updated_at"]}, versions


def _record_rows(publish_store) -> tuple[list[dict], list[dict], dict]:
    record = publish_store.get_json("record.json")
    if record is None:
        return [], [], {}
    if record.get("schema_version") != 2:
        raise ValueError(f"Unsupported prospective record schema: {record.get('schema_version')!r}")
    matches = []
    for state in ("pending", "settled"):
        for row in record.get(state, ()):
            matches.append(
                {
                    "record_state": state,
                    "match_id": row["match_id"],
                    "competition_id": row.get("competition_id"),
                    "season_id": row.get("season_id"),
                    "forecast_id": row["forecast_id"],
                    "generated_at": row.get("generated_at"),
                    "kickoff_time": row.get("kickoff_time"),
                    "model_version": row.get("model_version"),
                    "p_home": row.get("p_home"),
                    "p_draw": row.get("p_draw"),
                    "p_away": row.get("p_away"),
                    "outcome": row.get("outcome"),
                }
            )
    summaries = []
    for scope, value in record.get("summary", {}).items():
        if not isinstance(value, dict):
            continue
        summaries.append(
            {
                "scope": scope,
                "scored": value.get("scored"),
                "log_loss": value.get("log_loss"),
                "brier": value.get("brier"),
                "classwise_ece": value.get("classwise_ece"),
                "metrics": _json(value),
            }
        )
    return matches, summaries, {"record.json": record.get("updated_at")}


TEAM_COLUMNS = (
    ("team_id", "VARCHAR"),
    ("team_name", "VARCHAR"),
    ("played", "INTEGER"),
    ("current_points", "INTEGER"),
    ("mean_points", "DOUBLE"),
    ("median_points", "DOUBLE"),
    ("mean_position", "DOUBLE"),
    ("median_position", "DOUBLE"),
    ("position_sd", "DOUBLE"),
    ("mean_goal_difference", "DOUBLE"),
)


def _install_live(connection, rows: dict[str, list]) -> None:
    base = (("forecast_id", "VARCHAR"), ("competition_id", "VARCHAR"), ("season_id", "VARCHAR"))
    _create_table(
        connection,
        "forecasts",
        base
        + (
            ("generated_at", "TIMESTAMPTZ"),
            ("state_observed_at", "TIMESTAMPTZ"),
            ("model_results_cutoff", "DATE"),
            ("public_model_version", "VARCHAR"),
            ("private_model_id", "VARCHAR"),
            ("simulations", "INTEGER"),
            ("public_href", "VARCHAR"),
            ("private_prefix", "VARCHAR"),
        ),
        rows["forecasts"],
    )
    _create_table(
        connection,
        "forecast_matches",
        base
        + (
            ("match_id", "VARCHAR"),
            ("kickoff_time", "TIMESTAMPTZ"),
            ("match_date", "DATE"),
            ("home_team_id", "VARCHAR"),
            ("away_team_id", "VARCHAR"),
            ("status", "VARCHAR"),
            ("on_public_surface", "BOOLEAN"),
            ("structural_p_home", "DOUBLE"),
            ("structural_p_draw", "DOUBLE"),
            ("structural_p_away", "DOUBLE"),
            ("market_assisted_p_home", "DOUBLE"),
            ("market_assisted_p_draw", "DOUBLE"),
            ("market_assisted_p_away", "DOUBLE"),
            ("market_family", "VARCHAR"),
            ("market_observed_at", "TIMESTAMPTZ"),
            ("personnel", "JSON"),
            ("score_distribution", "JSON"),
        ),
        rows["forecast_matches"],
    )
    _create_table(connection, "forecast_teams", base + TEAM_COLUMNS, rows["forecast_teams"])
    _create_table(
        connection,
        "forecast_team_events",
        base + (("team_id", "VARCHAR"), ("event", "VARCHAR"), ("probability", "DOUBLE")),
        rows["forecast_team_events"],
    )
    _create_table(
        connection,
        "forecast_points_distribution",
        base + (("team_id", "VARCHAR"), ("points", "INTEGER"), ("probability", "DOUBLE")),
        rows["forecast_points_distribution"],
    )
    _create_table(
        connection,
        "forecast_position_distribution",
        base + (("team_id", "VARCHAR"), ("position", "INTEGER"), ("probability", "DOUBLE")),
        rows["forecast_position_distribution"],
    )
    _create_table(
        connection,
        "forecast_intervals",
        base
        + (
            ("team_id", "VARCHAR"),
            ("estimate", "VARCHAR"),
            ("level", "INTEGER"),
            ("lower", "DOUBLE"),
            ("upper", "DOUBLE"),
        ),
        rows["forecast_intervals"],
    )
    _create_table(
        connection,
        "model_team_states",
        base
        + (
            ("team_id", "VARCHAR"),
            ("quality", "DOUBLE"),
            ("attack_log_rate", "DOUBLE"),
            ("defense_log_rate", "DOUBLE"),
            ("attack_multiplier", "DOUBLE"),
            ("defense_multiplier", "DOUBLE"),
            ("training_matches", "INTEGER"),
            ("state", "JSON"),
        ),
        rows["model_team_states"],
    )
    _create_table(
        connection,
        "forecast_runs",
        base
        + (
            ("generated_at", "TIMESTAMPTZ"),
            ("model_id", "VARCHAR"),
            ("package_version", "VARCHAR"),
            ("code_sha256", "VARCHAR"),
            ("commit", "VARCHAR"),
            ("training_matches", "INTEGER"),
            ("fit_diagnostics", "JSON"),
            ("provenance", "JSON"),
        ),
        rows["forecast_runs"],
    )
    _create_table(
        connection,
        "forecast_impacts",
        base
        + (
            ("match_id", "VARCHAR"),
            ("event", "VARCHAR"),
            ("team_id", "VARCHAR"),
            ("outcome", "VARCHAR"),
            ("baseline", "DOUBLE"),
            ("conditional_probability", "DOUBLE"),
            ("rms_movement", "DOUBLE"),
            ("carried_from_forecast_id", "VARCHAR"),
            ("carried_from_generated_at", "TIMESTAMPTZ"),
        ),
        rows["forecast_impacts"],
    )


def _install_hindcasts(connection, rows: dict[str, list]) -> None:
    base = (
        ("hindcast_id", "VARCHAR"),
        ("competition_id", "VARCHAR"),
        ("season_id", "VARCHAR"),
        ("origin_at", "TIMESTAMPTZ"),
    )
    _create_table(
        connection,
        "hindcast_origins",
        base
        + (
            ("retrospective", "BOOLEAN"),
            ("generated_at", "TIMESTAMPTZ"),
            ("model_results_cutoff", "DATE"),
            ("model_version", "VARCHAR"),
            ("simulations", "INTEGER"),
            ("played_matches", "INTEGER"),
            ("remaining_matches", "INTEGER"),
            ("public_href", "VARCHAR"),
            ("private_key", "VARCHAR"),
        ),
        rows["hindcast_origins"],
    )
    _create_table(connection, "hindcast_teams", base + TEAM_COLUMNS, rows["hindcast_teams"])
    for suffix, value_column in (
        ("team_events", (("event", "VARCHAR"),)),
        ("points_distribution", (("points", "INTEGER"),)),
        ("position_distribution", (("position", "INTEGER"),)),
    ):
        _create_table(
            connection,
            f"hindcast_{suffix}",
            base + (("team_id", "VARCHAR"),) + value_column + (("probability", "DOUBLE"),),
            rows[f"hindcast_{suffix}"],
        )
    _create_table(
        connection,
        "hindcast_intervals",
        base
        + (
            ("team_id", "VARCHAR"),
            ("estimate", "VARCHAR"),
            ("level", "INTEGER"),
            ("lower", "DOUBLE"),
            ("upper", "DOUBLE"),
        ),
        rows["hindcast_intervals"],
    )


def _install_record(connection, matches: list[dict], summaries: list[dict]) -> None:
    _create_table(
        connection,
        "record_matches",
        (
            ("record_state", "VARCHAR"),
            ("match_id", "VARCHAR"),
            ("competition_id", "VARCHAR"),
            ("season_id", "VARCHAR"),
            ("forecast_id", "VARCHAR"),
            ("generated_at", "TIMESTAMPTZ"),
            ("kickoff_time", "TIMESTAMPTZ"),
            ("model_version", "VARCHAR"),
            ("p_home", "DOUBLE"),
            ("p_draw", "DOUBLE"),
            ("p_away", "DOUBLE"),
            ("outcome", "VARCHAR"),
        ),
        matches,
    )
    _create_table(
        connection,
        "record_summary",
        (
            ("scope", "VARCHAR"),
            ("scored", "INTEGER"),
            ("log_loss", "DOUBLE"),
            ("brier", "DOUBLE"),
            ("classwise_ece", "DOUBLE"),
            ("metrics", "JSON"),
        ),
        summaries,
    )


def _validate_analysis(connection) -> None:
    grains = {
        "forecasts": "forecast_id, competition_id",
        "forecast_matches": "forecast_id, competition_id, match_id",
        "forecast_teams": "forecast_id, competition_id, team_id",
        "forecast_team_events": "forecast_id, competition_id, team_id, event",
        "forecast_points_distribution": "forecast_id, competition_id, team_id, points",
        "forecast_position_distribution": "forecast_id, competition_id, team_id, position",
        "forecast_intervals": "forecast_id, competition_id, team_id, estimate, level",
        "model_team_states": "forecast_id, competition_id, team_id",
        "forecast_runs": "forecast_id, competition_id",
        "forecast_impacts": "forecast_id, competition_id, match_id, event, team_id, outcome",
        "hindcast_origins": "hindcast_id, competition_id, season_id",
        "hindcast_teams": "hindcast_id, competition_id, season_id, team_id",
        "hindcast_team_events": "hindcast_id, competition_id, season_id, team_id, event",
        "hindcast_points_distribution": "hindcast_id, competition_id, season_id, team_id, points",
        "hindcast_position_distribution": "hindcast_id, competition_id, season_id, team_id, position",
        "hindcast_intervals": "hindcast_id, competition_id, season_id, team_id, estimate, level",
        "record_matches": "record_state, match_id",
        "record_summary": "scope",
    }
    for table, keys in grains.items():
        duplicate = connection.execute(
            f"SELECT 1 FROM analysis.{table} GROUP BY {keys} HAVING count(*) > 1 LIMIT 1"
        ).fetchone()
        if duplicate:
            raise ValueError(f"Duplicate declared grain in analysis.{table}")
    probability_checks = {
        "forecast_matches": "abs(structural_p_home + structural_p_draw + structural_p_away - 1) > 0.000002 OR (market_assisted_p_home IS NOT NULL AND abs(market_assisted_p_home + market_assisted_p_draw + market_assisted_p_away - 1) > 0.000002)",
        "record_matches": "abs(p_home + p_draw + p_away - 1) > 0.000002",
    }
    for table, predicate in probability_checks.items():
        if connection.execute(
            f"SELECT 1 FROM analysis.{table} WHERE {predicate} LIMIT 1"
        ).fetchone():
            raise ValueError(f"Invalid probability sum in analysis.{table}")
    for prefix in ("forecast", "hindcast"):
        identity = (
            "forecast_id, competition_id, team_id"
            if prefix == "forecast"
            else ("hindcast_id, competition_id, season_id, team_id")
        )
        for distribution in ("points", "position"):
            if connection.execute(
                f"SELECT 1 FROM analysis.{prefix}_{distribution}_distribution "
                f"GROUP BY {identity} HAVING abs(sum(probability) - 1) > 0.0001 LIMIT 1"
            ).fetchone():
                raise ValueError(
                    f"Invalid distribution total in analysis.{prefix}_{distribution}_distribution"
                )
        missing_child = connection.execute(
            f"SELECT 1 FROM analysis.{prefix}_team_events child "
            f"LEFT JOIN analysis.{prefix}_teams parent USING ({identity}) "
            f"WHERE parent.team_id IS NULL LIMIT 1"
        ).fetchone()
        if missing_child:
            raise ValueError(f"Unknown team identity in analysis.{prefix}_team_events")


def install_artifact_analysis(connection, data_store, publish_store) -> tuple[dict, set[str]]:
    live, live_updates, live_versions = _live_rows(data_store, publish_store)
    hindcasts, hindcast_updates, hindcast_versions = _hindcast_rows(data_store, publish_store)
    record_matches, record_summary, record_updates = _record_rows(publish_store)
    _install_live(connection, live)
    _install_hindcasts(connection, hindcasts)
    _install_record(connection, record_matches, record_summary)
    _validate_analysis(connection)
    connection.execute(
        """
        CREATE VIEW analysis.team_projections AS
        SELECT 'live' AS product, false AS retrospective, f.forecast_id,
               NULL::VARCHAR AS hindcast_id, f.competition_id, f.season_id, f.generated_at,
               NULL::TIMESTAMPTZ AS origin_at, f.state_observed_at, f.model_results_cutoff,
               t.team_id, t.team_name, t.played, t.current_points, t.mean_points,
               t.median_points, t.mean_position, t.median_position, t.position_sd,
               t.mean_goal_difference
        FROM analysis.forecast_teams t JOIN analysis.forecasts f
        USING (forecast_id, competition_id, season_id)
        UNION ALL
        SELECT 'hindcast' AS product, true AS retrospective, NULL::VARCHAR AS forecast_id,
               h.hindcast_id, h.competition_id, h.season_id, h.generated_at, h.origin_at,
               NULL::TIMESTAMPTZ AS state_observed_at, h.model_results_cutoff,
               t.team_id, t.team_name, t.played, t.current_points, t.mean_points,
               t.median_points, t.mean_position, t.median_position, t.position_sd,
               t.mean_goal_difference
        FROM analysis.hindcast_teams t JOIN analysis.hindcast_origins h
        USING (hindcast_id, competition_id, season_id, origin_at)
        """
    )
    return (
        {**live_updates, **hindcast_updates, **record_updates},
        live_versions | hindcast_versions,
    )
