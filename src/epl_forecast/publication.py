"""Build and validate the small public forecast surface."""

import re
import shutil
import tempfile
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from epl_forecast.competitions import COMPETITION_IDS
from epl_forecast.datasets import timestamp
from epl_forecast.simulation import EVERY_TEAM, OUTCOME_NAMES
from epl_forecast.storage import json_bytes, sha256_bytes, write_json

POLICY_PATH = Path("configs/publication.toml")
MINIMUM_SIMULATIONS = 1000
# Expected movement below this is under a tenth of the smallest number the viewer shows.
IMPACT_MOVEMENT_FLOOR = 5e-5
CARRIED_FIELDS = (
    "outcome_counts",
    "sufficient_sample",
    "max_standard_error",
    "top_rms_movement",
    "impacts",
)
UNAVAILABLE_IMPACT = (
    "No published forecast before this kickoff covers every club, so no impact is shown."
)
DIGEST = re.compile(r"\b[0-9a-f]{32,}\b")
TEAM_FIELDS = (
    "team_id",
    "played",
    "current_points",
    "mean_points",
    "median_points",
    "points_intervals",
    "points_quantiles_05_50_95",
    "mean_position",
    "median_position",
    "position_sd",
    "position_intervals",
    "mean_goal_difference",
)

FORECAST_KEYS = {
    "away",
    "away_discontinuity",
    "away_rate",
    "away_team_id",
    "baseline",
    "basis",
    "carried_from",
    "competition_id",
    "competition_name",
    "conditional",
    "coverage",
    "current_points",
    "draw",
    "event",
    "events",
    "fixtures",
    "forecast_id",
    "generated_at",
    "grid_home_rows_away_columns",
    "home",
    "home_discontinuity",
    "home_log_rate_shift",
    "home_rate",
    "home_team_id",
    "horizon_days",
    "href",
    "impact",
    "impacts",
    "kickoff_time",
    "market_assisted",
    "match_date",
    "match_horizon_days",
    "match_id",
    "matches",
    "max_standard_error",
    "mean_goal_difference",
    "mean_points",
    "mean_position",
    "median_points",
    "median_position",
    "minimum_conditional_samples",
    "model",
    "model_results_cutoff",
    "movement_floor",
    "name",
    "omitted_probability",
    "outcome",
    "outcome_counts",
    "p_away",
    "p_draw",
    "p_home",
    "personnel",
    "played",
    "points_distribution",
    "points_intervals",
    "points_quantiles_05_50_95",
    "position_intervals",
    "position_probabilities",
    "position_sd",
    "release_href",
    "released_at",
    "rms_movement",
    "schema_version",
    "score_probabilities",
    "season_id",
    "simulated_on",
    "simulations",
    "smallest_outcome_count",
    "state_observed_at",
    "state_uncertainty",
    "status",
    "sufficient_sample",
    "team_id",
    "teams",
    "top_rms_movement",
    "unavailable_reason",
    "unscheduled_assumption",
    "unscheduled_fixtures",
    "unsettled_assumption",
    "unsettled_fixtures",
    "version",
    "window_end",
    "window_start",
}
POINTER_KEYS = {
    "document_sha256",
    "release_href",
    "released_at",
    "competition_id",
    "competition_name",
    "forecast_id",
    "forecasts",
    "generated_at",
    "href",
    "matches",
    "model_version",
    "schema_version",
    "season_id",
    "updated_at",
}
RECORD_KEYS = {
    "released_at",
    "brier",
    "classwise_ece",
    "competition_id",
    "forecast_id",
    "generated_at",
    "kickoff_time",
    "log_loss",
    "match_id",
    "model_version",
    "outcome",
    "overall",
    "p_away",
    "p_draw",
    "p_home",
    "pending",
    "schema_version",
    "scored",
    "season_id",
    "settled",
    "summary",
    "unsettled",
    "updated_at",
}
HINDCAST_KEYS = {
    "assumptions",
    "competition_id",
    "competition_name",
    "events",
    "hindcast_id",
    "model",
    "model_results_cutoff",
    "name",
    "notice",
    "origin_at",
    "played_matches",
    "points_distribution",
    "position_probabilities",
    "product",
    "remaining_matches",
    "retrospective",
    "schema_version",
    "season_id",
    "simulations",
    "state_uncertainty",
    "teams",
    "version",
    *TEAM_FIELDS,
}
HINDCAST_SERIES_KEYS = HINDCAST_KEYS | {"href", "origins"}
HINDCAST_INDEX_KEYS = {
    "competition_id",
    "competition_name",
    "first_origin_at",
    "href",
    "last_origin_at",
    "model_version",
    "notice",
    "origin_count",
    "product",
    "retrospective",
    "schema_version",
    "season_id",
    "seasons",
    "updated_at",
}
# A retrospective match forecast. It scores one match, so it carries no season projection and
# no simulation. It never enters the prospective record: `prospective_from` states the London day
# on which live coverage of the model version began, and every match here is earlier.
MATCH_HINDCAST_KEYS = {
    "assumptions",
    "deferred_fixtures",
    "status",
    "away_discontinuity",
    "away_rate",
    "away_team_id",
    "competition_id",
    "competition_name",
    "grid_home_rows_away_columns",
    "home_discontinuity",
    "home_log_rate_shift",
    "home_rate",
    "home_team_id",
    "kickoff_time",
    "last_match_date",
    "match_date",
    "match_id",
    "matches",
    "model",
    "model_results_cutoff",
    "notice",
    "omitted_probability",
    "origin_at",
    "origin_rule",
    "p_away",
    "p_draw",
    "p_home",
    "personnel",
    "product",
    "prospective_from",
    "retrospective",
    "schema_version",
    "score_probabilities",
    "season_id",
    "unadjusted",
    "version",
}
MATCH_HINDCAST_INDEX_KEYS = {
    "competition_id",
    "deferred_count",
    "competition_name",
    "first_match_date",
    "href",
    "last_match_date",
    "match_count",
    "model_version",
    "notice",
    "product",
    "prospective_from",
    "retrospective",
    "schema_version",
    "season_id",
    "seasons",
    "updated_at",
}
CONTRACT_KEYS = {
    "forecast": FORECAST_KEYS,
    "current": POINTER_KEYS,
    "archive": POINTER_KEYS,
    "record": RECORD_KEYS,
    "hindcast": HINDCAST_KEYS,
    "hindcast_series": HINDCAST_SERIES_KEYS,
    "hindcast_index": HINDCAST_INDEX_KEYS,
    "match_hindcast": MATCH_HINDCAST_KEYS,
    "match_hindcast_index": MATCH_HINDCAST_INDEX_KEYS,
}
# A hindcast is retrospective. Its documents stay under their own prefix, so no live pointer can name one.
NAMESPACES = {
    "current": "forecasts/",
    "archive": "forecasts/",
    "hindcast_series": "hindcasts/",
    "hindcast_index": "hindcasts/",
    "match_hindcast_index": "match-hindcasts/",
}


def load_policy(path: Path = POLICY_PATH) -> dict:
    with Path(path).open("rb") as stream:
        policy = tomllib.load(stream)
    forbidden = policy["boundary"]["forbidden_key_substrings"]
    leaked = sorted(
        key
        for keys in CONTRACT_KEYS.values()
        for key in keys
        if any(substring in key for substring in forbidden)
    )
    if leaked:
        raise ValueError(f"Publication allowlist contradicts the boundary: {leaked}")
    return policy


def document_kind(document: dict) -> str:
    if document.get("product") == "match_hindcast":
        return "match_hindcast_index" if "seasons" in document else "match_hindcast"
    if document.get("product") == "hindcast":
        if "origins" in document:
            return "hindcast_series"
        if "teams" in document:
            return "hindcast"
        if "seasons" in document:
            return "hindcast_index"
        raise ValueError("Unknown hindcast document type")
    if "teams" in document:
        return "forecast"
    if "forecasts" in document:
        return "archive" if "competition_id" in document else "current"
    if "settled" in document:
        return "record"
    raise ValueError("Unknown public document type")


def check_publishable(document, policy: dict, kind: str | None = None) -> None:
    kind = kind or document_kind(document)
    allowed = CONTRACT_KEYS[kind]
    forbidden = policy["boundary"]["forbidden_key_substrings"]
    patterns = [re.compile(p) for p in policy["boundary"]["forbidden_value_patterns"]]

    def walk(node, trail, key=None):
        if isinstance(node, dict):
            for name, value in node.items():
                if any(substring in name for substring in forbidden):
                    raise ValueError(f"Private key on the published surface: {trail}.{name}")
                if name not in allowed and not _is_open_map(trail):
                    raise ValueError(f"Key is not in the {kind} contract: {trail}.{name}")
                if (
                    name == "href"
                    and kind in NAMESPACES
                    and not str(value).startswith(NAMESPACES[kind])
                ):
                    raise ValueError(
                        f"A {kind} document can only link under {NAMESPACES[kind]}: {trail}.{name}"
                    )
                walk(value, f"{trail}.{name}", name)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{trail}[{index}]", key)
        elif isinstance(node, str):
            for pattern in patterns:
                if pattern.search(node):
                    raise ValueError(f"Private value on the published surface: {trail} ({node!r})")
            if DIGEST.search(node) and key != "document_sha256":
                raise ValueError(f"Unexpected digest on the published surface: {trail}")

    walk(document, "$")


def _is_open_map(trail: str) -> bool:
    return trail.endswith(
        (
            ".points_distribution",
            ".events",
            ".impacts",
            ".summary",
            ".points_intervals",
            ".position_intervals",
        )
    )


def probability(value) -> float:
    return round(float(value), 6)


def _number(value):
    return round(float(value), 3) if isinstance(value, float) else value


def _compact(value):
    if isinstance(value, list):
        return [_compact(item) for item in value]
    if isinstance(value, dict):
        return {key: _compact(item) for key, item in value.items()}
    return _number(value)


def _distribution(mapping: dict) -> dict:
    kept = {key: probability(value) for key, value in mapping.items() if float(value) >= 5e-7}
    return {key: kept[key] for key in sorted(kept, key=int)}


def _impact_columns(fixture: dict, floor: float) -> tuple[dict, float]:
    """Group a fixture's rows by event, as parallel arrays in movement order.

    One array of club IDs and one array for each result carries the same rows as a list
    of records, without repeating a key on every club. A club whose expected movement is
    below the floor is left out; its event probability is unchanged by this fixture and
    is published with the club itself.
    """
    columns, worst_error = {}, 0.0
    for row in fixture["impacts"]:
        errors = [value for value in row["standard_error"].values() if value is not None]
        if errors:
            worst_error = max(worst_error, max(errors))
        if row["rms_movement"] < floor:
            continue
        block = columns.setdefault(
            row["event"],
            {"team_id": [], **{name: [] for name in OUTCOME_NAMES}, "rms_movement": []},
        )
        block["team_id"].append(row["team_id"])
        for name in OUTCOME_NAMES:
            value = row["conditional"][name]
            block[name].append(None if value is None else probability(value))
        block["rms_movement"].append(probability(row["rms_movement"]))
    return columns, probability(worst_error)


def derive_impact(simulation: dict, kickoffs: dict, window: dict | None = None) -> dict | None:
    """Publish the weekly slate: every club's movement against every fixture in it.

    The viewer ranks one club and one event at a time, so it needs each fixture measured
    against each club rather than a precomputed leaderboard. The baseline of a fixture
    that is still to be played is the club's own event probability in this document, so
    it is not repeated here. A fixture that already finished carries no numbers yet;
    `carry_forward_impacts` fills it from the last forecast made before its kickoff.
    These are aggregates only: no path-level data.
    """
    impacts = simulation.get("match_impacts")
    if not impacts:
        return None
    window = window or {}
    published = []
    for fixture in impacts["fixtures"]:
        columns, worst_error = _impact_columns(fixture, IMPACT_MOVEMENT_FLOOR)
        counts = fixture["outcome_counts"]
        published.append(
            {
                "match_id": fixture["match_id"],
                "match_date": fixture["match_date"],
                "kickoff_time": kickoffs.get(fixture["match_id"]),
                "home_team_id": fixture["home_team_id"],
                "away_team_id": fixture["away_team_id"],
                "status": "scheduled",
                "outcome": None,
                "outcome_counts": counts,
                "sufficient_sample": min(counts.values()) >= impacts["minimum_conditional_samples"],
                "max_standard_error": worst_error,
                "top_rms_movement": probability(fixture["top_rms_movement"]),
                "carried_from": None,
                "impacts": columns,
            }
        )
    for row in window.get("started", []):
        published.append(
            {
                "match_id": row["match_id"],
                "match_date": row["match_date"],
                "kickoff_time": row["kickoff_time"],
                "home_team_id": row["home_team_id"],
                "away_team_id": row["away_team_id"],
                "status": row["status"],
                "outcome": row["outcome"],
                "carried_from": None,
                "unavailable_reason": UNAVAILABLE_IMPACT,
                "impacts": {},
            }
        )
    published.sort(key=lambda row: (row["kickoff_time"] or "9999", row["match_id"]))
    return {
        "horizon_days": impacts["horizon_days"],
        "window_start": window.get("window_start") or impacts.get("window_start"),
        "window_end": window.get("window_end") or impacts.get("window_end"),
        "coverage": impacts.get("coverage", "participants"),
        "minimum_conditional_samples": impacts["minimum_conditional_samples"],
        "smallest_outcome_count": impacts["smallest_outcome_count"],
        "movement_floor": IMPACT_MOVEMENT_FLOOR,
        "basis": impacts["basis"],
        "fixtures": published,
    }


def update_impact_state(document: dict, state: dict) -> dict:
    """Carry eligible impact rows forward and retain only active match candidates."""
    impact = document.get("impact")
    if not impact:
        return document
    candidates = state.setdefault("matches", {})
    fixtures = []
    events = {team["team_id"]: team["events"] for team in document["teams"]}
    generated = timestamp(document["generated_at"])
    for fixture in impact["fixtures"]:
        match_id = fixture["match_id"]
        record = candidates.get(match_id) if fixture["status"] != "scheduled" else None
        if record:
            fixture = {
                **{key: value for key, value in fixture.items() if key != "unavailable_reason"},
                **{key: record[key] for key in CARRIED_FIELDS},
                "carried_from": {
                    "forecast_id": record["forecast_id"],
                    "generated_at": record["generated_at"],
                },
            }
            if fixture["status"] == "finished":
                candidates.pop(match_id)
        elif (
            fixture["status"] == "scheduled"
            and fixture["kickoff_time"]
            and impact.get("coverage") == EVERY_TEAM
            and generated < timestamp(fixture["kickoff_time"])
        ):
            candidates[match_id] = {
                "forecast_id": document["forecast_id"],
                "generated_at": document["generated_at"],
                **{key: fixture[key] for key in CARRIED_FIELDS},
                "impacts": {
                    event: {
                        **block,
                        "baseline": [events.get(team, {}).get(event) for team in block["team_id"]],
                    }
                    for event, block in fixture["impacts"].items()
                },
            }
        fixtures.append(fixture)
    return {**document, "impact": {**impact, "fixtures": fixtures}}


def season_team_rows(rows: list[dict], names: dict) -> list[dict]:
    """The published season estimates of each club, in expected table order."""
    return [
        {
            **{field: _compact(row[field]) for field in TEAM_FIELDS},
            "name": names.get(row["team_id"], row["team_id"]),
            "position_probabilities": [probability(p) for p in row["position_probabilities"]],
            "points_distribution": _distribution(row["points_distribution"]),
            "events": {
                key: probability(value)
                for key, value in sorted(row.items())
                if key.endswith("_probability")
            },
        }
        for row in sorted(rows, key=lambda row: row["mean_position"])
    ]


def public_personnel(record: dict | None) -> dict | None:
    """The matchday-squad discontinuity of each club and the home log-rate shift it gives."""
    if record is None:
        return None

    def rounded(value):
        return None if value is None else round(float(value), 6)

    return {
        "home_discontinuity": rounded(record["home"]["discontinuity"]),
        "away_discontinuity": rounded(record["away"]["discontinuity"]),
        "home_log_rate_shift": rounded(record["home_log_rate_shift"]),
    }


def derive_forecast(
    forecast: dict,
    forecast_id: str,
    horizon_days: int = 21,
    public_model_version: str = "v0.0",
) -> dict:
    simulation = forecast["simulation"]
    if simulation is None:
        raise ValueError(
            f"Refusing to publish a forecast without a season projection: {forecast_id}"
        )
    if simulation["simulations"] < MINIMUM_SIMULATIONS:
        raise ValueError(
            f"Refusing to publish {simulation['simulations']} simulated paths; the product floor is {MINIMUM_SIMULATIONS}"
        )
    teams = season_team_rows(simulation["teams"], forecast["team_names"])
    matches = []
    horizon = timestamp(forecast["generated_at"]) + timedelta(days=horizon_days)
    for row in forecast["matches"]:
        if row["status"] != "scheduled" or not row["kickoff_time"]:
            continue
        if timestamp(row["kickoff_time"]) > horizon and not row["next_match_for_teams"]:
            continue
        assisted = row["market_assisted_probabilities"]
        published = {
            "match_id": row["match_id"],
            "kickoff_time": row["kickoff_time"],
            "match_date": row["match_date"],
            "home_team_id": row["home_team_id"],
            "away_team_id": row["away_team_id"],
            "status": row["status"],
            "p_home": probability(row["p_home"]),
            "p_draw": probability(row["p_draw"]),
            "p_away": probability(row["p_away"]),
            "market_assisted": None
            if assisted is None
            else {key: probability(assisted[key]) for key in ("p_home", "p_draw", "p_away")},
            "personnel": public_personnel(row["personnel"]),
        }
        if row["next_match_for_teams"]:
            scores = row["score_distribution"]
            published["score_probabilities"] = {
                "home_rate": round(float(scores["home_rate"]), 6),
                "away_rate": round(float(scores["away_rate"]), 6),
                "omitted_probability": probability(scores["omitted_probability"]),
                "grid_home_rows_away_columns": [
                    [probability(cell) for cell in line]
                    for line in scores["grid_home_rows_away_columns"]
                ],
            }
        matches.append(published)
    # A postponed or undated fixture still enters the season paths, so say where it was placed.
    unscheduled = [
        {
            "match_id": row["match_id"],
            "home_team_id": row["home_team_id"],
            "away_team_id": row["away_team_id"],
            "match_date": row["match_date"],
            "simulated_on": row["model_forecast_date"],
        }
        for row in forecast["matches"]
        if row["status"] == "unscheduled"
    ]
    document = {
        "schema_version": 3,
        "forecast_id": forecast_id,
        "competition_id": forecast["competition_id"],
        "competition_name": forecast["competition_name"],
        "season_id": forecast["season_id"],
        "generated_at": forecast["generated_at"],
        "state_observed_at": forecast["state_observed_at"],
        "model_results_cutoff": forecast["model_results_cutoff"],
        "state_uncertainty": forecast["state_uncertainty"],
        "simulations": simulation["simulations"],
        "match_horizon_days": horizon_days,
        "model": {"version": public_model_version},
        "teams": teams,
        "matches": matches,
        "unscheduled_fixtures": unscheduled,
        "unscheduled_assumption": forecast.get("unscheduled_placeholder") if unscheduled else None,
        "unsettled_fixtures": [
            {
                key: row[key]
                for key in (
                    "match_id",
                    "home_team_id",
                    "away_team_id",
                    "match_date",
                    "kickoff_time",
                    "status",
                )
            }
            for row in forecast.get("unsettled_fixtures", [])
        ],
        "unsettled_assumption": forecast.get("unsettled_placeholder"),
        "impact": derive_impact(
            simulation,
            {row["match_id"]: row["kickoff_time"] for row in matches},
            forecast.get("impact_window"),
        ),
    }
    return document


def _competition_order(row: dict) -> tuple[int, str]:
    competition_id = row["competition_id"]
    return (
        COMPETITION_IDS.index(competition_id)
        if competition_id in COMPETITION_IDS
        else len(COMPETITION_IDS),
        competition_id,
    )


def empty_current(updated_at: str | None = None) -> dict:
    return {
        "schema_version": 1,
        "updated_at": updated_at or datetime.now(UTC).isoformat(),
        "forecasts": [],
    }


def empty_archive(competition_id: str, updated_at: str | None = None) -> dict:
    return {
        "schema_version": 1,
        "updated_at": updated_at or datetime.now(UTC).isoformat(),
        "competition_id": competition_id,
        "forecasts": [],
    }


def forecast_pointer(document: dict, document_sha256: str | None = None) -> dict:
    competition_id = document["competition_id"]
    forecast_id = document["forecast_id"]
    pointer = {
        "competition_id": competition_id,
        "competition_name": document["competition_name"],
        "season_id": document["season_id"],
        "forecast_id": forecast_id,
        "generated_at": document["generated_at"],
        "model_version": document["model"]["version"],
        "matches": len(document["matches"]),
        "href": f"forecasts/{competition_id}/{forecast_id}.json",
    }
    if document_sha256 is not None:
        pointer["document_sha256"] = document_sha256
    return pointer


def _versioned(store, key: str, default):
    return store.get_json_versioned(key, default)


def publish_documents(store, documents: list[dict], policy: dict) -> dict:
    current, current_version = _versioned(store, "forecasts/current.json", empty_current())
    latest = {row["competition_id"]: row for row in current["forecasts"]}
    archives = {}
    for document in documents:
        if document.get("retrospective") or document.get("product") == "hindcast":
            raise ValueError("A hindcast cannot enter the live forecast pointers")
        issued = {
            key: value
            for key, value in document.items()
            if key not in {"release_href", "released_at"}
        }
        check_publishable(issued, policy, "forecast")
        document_key = f"forecasts/{document['competition_id']}/{document['forecast_id']}.json"
        document_sha256 = sha256_bytes(json_bytes(issued))
        store.put_json(document_key, issued, immutable=True)
        receipt_key = f"commitments/{document['competition_id']}/{document['forecast_id']}.json"
        receipt = store.get_json(receipt_key)
        if receipt is None:
            receipt = {
                "schema_version": 2,
                "competition_id": document["competition_id"],
                "forecast_id": document["forecast_id"],
                "document_href": document_key,
                "document_sha256": document_sha256,
                "committed_at": datetime.now(UTC).isoformat(),
            }
            try:
                store.put_json(receipt_key, receipt, immutable=True)
            except ValueError:
                receipt = store.get_json(receipt_key)
                if receipt is None:
                    raise
        if receipt["document_sha256"] != document_sha256:
            raise ValueError("Commitment receipt names different forecast content")
        pointer = forecast_pointer(document, document_sha256)
        competition_id = document["competition_id"]
        archive_key = f"forecasts/{competition_id}/archive.json"
        archive, archive_version = _versioned(store, archive_key, empty_archive(competition_id))
        entries = {row["forecast_id"]: row for row in archive["forecasts"]}
        entries[pointer["forecast_id"]] = pointer
        archives[archive_key] = (
            {
                **archive,
                "updated_at": datetime.now(UTC).isoformat(),
                "forecasts": sorted(
                    entries.values(), key=lambda row: row["forecast_id"], reverse=True
                ),
            },
            archive_version,
        )
        latest[competition_id] = pointer
    for key, (archive, version) in archives.items():
        check_publishable(archive, policy, "archive")
        store.put_json_if(key, archive, version)
    result = {
        "schema_version": 1,
        "updated_at": datetime.now(UTC).isoformat(),
        "forecasts": sorted(latest.values(), key=_competition_order),
    }
    check_publishable(result, policy, "current")
    store.put_json_if("forecasts/current.json", result, current_version)
    forecasts = []
    for pointer in result["forecasts"]:
        digest = pointer.get("document_sha256")
        if digest is None:
            digest = sha256_bytes(json_bytes(store.get_json(pointer["href"])))
        forecasts.append(
            {
                "competition_id": pointer["competition_id"],
                "forecast_id": pointer["forecast_id"],
                "document_href": pointer["href"],
                "document_sha256": digest,
            }
        )
    revision_id = sha256_bytes(json_bytes(forecasts))
    revision = {
        "schema_version": 1,
        "revision_id": revision_id,
        "forecasts": forecasts,
    }
    store.put_json(f"deployments/revisions/{revision_id}.json", revision, immutable=True)
    desired, desired_version = store.get_json_versioned("deployments/desired.json")
    if desired is None or desired.get("revision_id") != revision_id:
        store.put_json_if(
            "deployments/desired.json",
            {**revision, "desired_at": datetime.now(UTC).isoformat()},
            desired_version,
        )
    return result


def activate_publication(
    store,
    revision_id: str,
    *,
    activated_at: datetime | None = None,
    page_url: str | None = None,
) -> dict:
    desired = store.get_json("deployments/desired.json")
    if desired is None or desired.get("revision_id") != revision_id:
        raise ValueError("The deployed revision is not the desired publication revision")
    activated_at = activated_at or datetime.now(UTC)
    activation = {
        **desired,
        "activated_at": activated_at.isoformat(),
        "page_url": page_url,
    }
    for forecast in desired["forecasts"]:
        receipt_key = f"availability/{forecast['competition_id']}/{forecast['forecast_id']}.json"
        existing = store.get_json(receipt_key)
        if existing is not None:
            if existing["document_sha256"] != forecast["document_sha256"]:
                raise ValueError("Availability receipt names different forecast content")
            continue
        receipt = {
            "schema_version": 1,
            **forecast,
            "revision_id": revision_id,
            "activated_at": activated_at.isoformat(),
        }
        store.put_json(receipt_key, receipt, immutable=True)
    store.put_json(f"deployments/activations/{revision_id}.json", activation, immutable=True)
    current, version = store.get_json_versioned("deployments/current.json")
    if current is None or current.get("revision_id") != revision_id:
        store.put_json_if("deployments/current.json", activation, version)
    return activation


def deployment_pending(store) -> bool:
    desired = store.get_json("deployments/desired.json")
    current = store.get_json("deployments/current.json")
    return desired is not None and (
        current is None or current.get("revision_id") != desired.get("revision_id")
    )


def activated_documents(store) -> list[dict]:
    activation = store.get_json("deployments/current.json")
    if activation is None:
        return []
    documents = []
    for forecast in activation["forecasts"]:
        document = store.get_json(forecast["document_href"])
        if sha256_bytes(json_bytes(document)) != forecast["document_sha256"]:
            raise ValueError("Activated publication content does not match its receipt")
        receipt = store.get_json(
            f"availability/{forecast['competition_id']}/{forecast['forecast_id']}.json"
        )
        if receipt is None or receipt["document_sha256"] != forecast["document_sha256"]:
            raise ValueError("Activated forecast has no matching availability receipt")
        documents.append({**document, "released_at": receipt["activated_at"]})
    return documents


def archive_documents(store, competition_id: str):
    archive = store.get_json(
        f"forecasts/{competition_id}/archive.json", empty_archive(competition_id)
    )
    for entry in reversed(archive["forecasts"]):
        document = store.get_json(entry["href"])
        receipt = store.get_json(f"availability/{competition_id}/{entry['forecast_id']}.json")
        if receipt:
            document = {**document, "released_at": receipt["activated_at"]}
        yield document


def materialize_publication(
    store, site: Path, archive_competitions: tuple[str, ...] = (), hindcasts: bool = False
) -> dict:
    site = Path(site)
    site.mkdir(parents=True, exist_ok=True)
    target = site / "data"
    hindcast_marker = site / ".page324-hindcast-cache"
    policy = load_policy()
    with tempfile.TemporaryDirectory(prefix=".publication-", dir=site) as temporary:
        data = Path(temporary)
        current = store.get_json("forecasts/current.json", empty_current())
        check_publishable(current, policy, "current")
        write_json(data / "current.json", current)
        written = set()

        def materialize(entry: dict) -> None:
            if entry["href"] in written:
                return
            document = store.get_json(entry["href"])
            check_publishable(document, policy, "forecast")
            write_json(data / entry["href"], document)
            written.add(entry["href"])

        for entry in current["forecasts"]:
            materialize(entry)
        for competition_id in archive_competitions:
            key = f"forecasts/{competition_id}/archive.json"
            archive = store.get_json(key, empty_archive(competition_id))
            check_publishable(archive, policy, "archive")
            write_json(data / key, archive)
            for entry in archive["forecasts"]:
                materialize(entry)
        hindcast_documents = 0
        if hindcasts:
            index = store.get_json("hindcasts/index.json")
            if index is not None:
                check_publishable(index, policy, "hindcast_index")
                index_identity = sha256_bytes(json_bytes(index))
                cached = (
                    target / "hindcasts"
                    if hindcast_marker.exists()
                    and hindcast_marker.read_text() == index_identity
                    and (target / "hindcasts").is_dir()
                    else None
                )
                if cached is not None:
                    shutil.copytree(cached, data / "hindcasts")
                write_json(data / "hindcasts/index.json", index)
                if cached is None:
                    for season in index["seasons"]:
                        series = store.get_json(season["href"])
                        check_publishable(series, policy, "hindcast_series")
                        write_json(data / season["href"], series)
                        for origin in series["origins"]:
                            document = store.get_json(origin["href"])
                            check_publishable(document, policy, "hindcast")
                            write_json(data / origin["href"], document)
                            hindcast_documents += 1
                else:
                    hindcast_documents = sum(
                        season.get("origin_count", 0) for season in index["seasons"]
                    )
        record = store.get_json("record.json")
        if record is not None:
            check_publishable(record, policy, "record")
            write_json(data / "record.json", record)
        if target.exists():
            shutil.rmtree(target)
        data.replace(target)
        if hindcasts and index is not None:
            hindcast_marker.write_text(index_identity)
    return {
        "documents": len(written),
        "archives": len(archive_competitions),
        "hindcasts": hindcast_documents,
        "record": record is not None,
    }
