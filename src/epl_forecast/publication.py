"""The compact derived surface that may leave this machine.

A published document is built only from model output: probabilities, season
distributions, event masses, timestamps and model identity. Provider payloads,
captured odds, request records, local file hashes and player tables stay in the
private archive. `configs/publication.toml` declares the allowlist, every
document is assembled from it by construction, and `check_publishable` re-checks
the assembled result so a careless addition fails loudly instead of shipping.
"""

import json
import re
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from epl_forecast.competitions import COMPETITION_IDS
from epl_forecast.datasets import timestamp
from epl_forecast.simulation import EVERY_TEAM, OUTCOME_NAMES
from epl_forecast.storage import json_bytes, write_immutable, write_json

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


def load_policy(path: Path = POLICY_PATH) -> dict:
    with Path(path).open("rb") as stream:
        policy = tomllib.load(stream)
    forbidden = policy["boundary"]["forbidden_key_substrings"]
    leaked = sorted(
        key
        for key in policy["surface"]["allowed_keys"]
        if any(substring in key for substring in forbidden)
    )
    if leaked:
        raise ValueError(f"Publication allowlist contradicts the boundary: {leaked}")
    return policy


def check_publishable(document, policy: dict) -> None:
    allowed = set(policy["surface"]["allowed_keys"])
    digest_keys = set(policy["surface"]["digest_keys"])
    forbidden = policy["boundary"]["forbidden_key_substrings"]
    patterns = [re.compile(p) for p in policy["boundary"]["forbidden_value_patterns"]]

    def walk(node, trail, key=None):
        if isinstance(node, dict):
            for name, value in node.items():
                if any(substring in name for substring in forbidden):
                    raise ValueError(f"Private key on the published surface: {trail}.{name}")
                if name not in allowed and not _is_open_map(trail):
                    raise ValueError(f"Key is not on the publication allowlist: {trail}.{name}")
                walk(value, f"{trail}.{name}", name)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{trail}[{index}]", key)
        elif isinstance(node, str):
            for pattern in patterns:
                if pattern.search(node):
                    raise ValueError(f"Private value on the published surface: {trail} ({node!r})")
            if DIGEST.search(node) and key not in digest_keys:
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
            ".latest_by_competition",
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


def last_pre_kickoff(site: Path, extract) -> dict:
    """The last record published for each match before that match kicked off.

    One cutoff rule serves the prospective ledger and the carried-forward impacts: a
    snapshot counts for a match only when it was generated strictly before the kickoff.
    `extract` reads the records of interest out of one published document.
    """
    latest = {}
    for document in published_documents(site):
        generated = timestamp(document["generated_at"])
        for match_id, kickoff, record in extract(document):
            if not kickoff or generated >= timestamp(kickoff):
                continue
            current = latest.get(match_id)
            if current and timestamp(current["generated_at"]) >= generated:
                continue
            latest[match_id] = {
                "snapshot_id": document["snapshot_id"],
                "generated_at": document["generated_at"],
                **record,
            }
    return latest


def _all_team_impacts(competition_id: str, wanted: set[str]):
    """Read all-club impact records for the wanted matches out of one published document."""

    def extract(document):
        impact = document.get("impact") or {}
        if document["competition_id"] != competition_id or impact.get("coverage") != EVERY_TEAM:
            return
        events = {team["team_id"]: team["events"] for team in document["teams"]}
        for fixture in impact["fixtures"]:
            # Only a snapshot that still had the match to play holds a pre-match record of it.
            # A carried record, and a fixture that snapshot could not measure either, hold none.
            if fixture["match_id"] not in wanted or fixture["status"] != "scheduled":
                continue
            record = {key: fixture[key] for key in CARRIED_FIELDS}
            # The baseline of a carried record is the one that stood before the kickoff.
            record["impacts"] = {
                event: {
                    **block,
                    "baseline": [events.get(team, {}).get(event) for team in block["team_id"]],
                }
                for event, block in fixture["impacts"].items()
            }
            yield fixture["match_id"], fixture["kickoff_time"], record

    return extract


def carry_forward_impacts(site: Path, document: dict) -> dict:
    """Fill each finished fixture of the slate from its last pre-kickoff all-club record.

    A finished match is not measured again on the current paths. Once the result is
    known, conditioning those paths on another result is no longer a pre-match
    statement. The carried record names the snapshot it comes from. A fixture with no
    eligible record keeps its disclosure instead of a number.
    """
    impact = document.get("impact")
    if not impact:
        return document
    wanted = {
        fixture["match_id"] for fixture in impact["fixtures"] if fixture["status"] != "scheduled"
    }
    if not wanted:
        return document
    archived = last_pre_kickoff(site, _all_team_impacts(document["competition_id"], wanted))
    fixtures = []
    for fixture in impact["fixtures"]:
        record = archived.get(fixture["match_id"]) if fixture["status"] != "scheduled" else None
        if record:
            fixture = {
                **{key: value for key, value in fixture.items() if key != "unavailable_reason"},
                **{key: record[key] for key in CARRIED_FIELDS},
                "carried_from": {
                    "snapshot_id": record["snapshot_id"],
                    "generated_at": record["generated_at"],
                },
            }
        fixtures.append(fixture)
    return {**document, "impact": {**impact, "fixtures": fixtures}}


def derive_forecast(
    forecast: dict,
    run: dict,
    snapshot_id: str,
    verification: dict | None = None,
    horizon_days: int = 21,
    public_model_version: str = "v0.0",
) -> dict:
    simulation = forecast["simulation"]
    if simulation is None:
        raise ValueError(
            f"Refusing to publish a forecast without a season projection: {snapshot_id}"
        )
    if simulation["simulations"] < MINIMUM_SIMULATIONS:
        raise ValueError(
            f"Refusing to publish {simulation['simulations']} simulated paths; the product floor is {MINIMUM_SIMULATIONS}"
        )
    names = forecast["team_names"]
    teams = []
    for row in sorted(simulation["teams"], key=lambda row: row["mean_position"]):
        teams.append(
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
        )
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
        "schema_version": 2,
        "snapshot_id": snapshot_id,
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


def write_derived(path: Path, value: dict) -> dict:
    """Write a rebuilt document, keeping the old one when only its timestamp moved."""
    if path.exists():
        existing = json.loads(path.read_text())
        if {k: v for k, v in existing.items() if k != "archived_at"} == {
            k: v for k, v in value.items() if k != "archived_at"
        }:
            return existing
    write_json(path, value)
    return value


def snapshot_directory(site: Path, snapshot_id: str) -> Path:
    return Path(site) / "data" / "forecasts" / snapshot_id


def publish_document(site: Path, document: dict, policy: dict) -> Path:
    check_publishable(document, policy)
    target = (
        snapshot_directory(site, document["snapshot_id"]) / f"{document['competition_id']}.json"
    )
    write_immutable(target, json_bytes(document))
    return target


def rebuild_index(site: Path, policy: dict) -> dict:
    site = Path(site)
    root = site / "data" / "forecasts"
    snapshots = []
    for directory in sorted(p for p in root.glob("*") if p.is_dir()):
        competitions = []
        for path in sorted(directory.glob("*.json")):
            document = json.loads(path.read_text())
            competitions.append(
                {
                    "competition_id": document["competition_id"],
                    "competition_name": document["competition_name"],
                    "season_id": document["season_id"],
                    "model_version": document["model"].get(
                        "version", policy["product"]["model_version"]
                    ),
                    "matches": len(document["matches"]),
                    "href": path.relative_to(site / "data").as_posix(),
                }
            )
            generated = document["generated_at"]
        # Pyramid order, so the viewer opens on the top division.
        competitions.sort(
            key=lambda row: (
                COMPETITION_IDS.index(row["competition_id"])
                if row["competition_id"] in COMPETITION_IDS
                else len(COMPETITION_IDS),
                row["competition_id"],
            )
        )
        if competitions:
            snapshots.append(
                {
                    "snapshot_id": directory.name,
                    "generated_at": generated,
                    "competitions": competitions,
                }
            )
    snapshots.sort(key=lambda row: row["snapshot_id"], reverse=True)
    index = {
        "schema_version": 1,
        "archived_at": datetime.now(UTC).isoformat(),
        "latest": snapshots[0]["snapshot_id"] if snapshots else None,
        "snapshots": snapshots,
    }
    check_publishable(index, policy)
    return write_derived(site / "data" / "index.json", index)


def published_documents(site: Path):
    for path in sorted((Path(site) / "data" / "forecasts").glob("*/*.json")):
        yield json.loads(path.read_text())


def empty_index(namespace: str, updated_at: str | None = None) -> dict:
    return {
        "schema_version": 2,
        "updated_at": updated_at or datetime.now(UTC).isoformat(),
        "namespace": namespace,
        "latest_by_competition": {},
        "snapshots": [],
    }


def publish_documents_to_store(store, documents: list[dict], policy: dict) -> dict:
    index = store.get_json("forecasts/index.json", empty_index("forecasts"))
    snapshots = {row["snapshot_id"]: row for row in index.get("snapshots", [])}
    for document in documents:
        check_publishable(document, policy)
        key = f"forecasts/{document['snapshot_id']}/{document['competition_id']}.json"
        store.put_json(key, document, immutable=True)
        snapshot = snapshots.setdefault(
            document["snapshot_id"],
            {
                "snapshot_id": document["snapshot_id"],
                "generated_at": document["generated_at"],
                "competitions": [],
            },
        )
        entry = {
            "competition_id": document["competition_id"],
            "competition_name": document["competition_name"],
            "season_id": document["season_id"],
            "model_version": document["model"]["version"],
            "matches": len(document["matches"]),
            "href": key,
        }
        snapshot["competitions"] = [
            row
            for row in snapshot["competitions"]
            if row["competition_id"] != document["competition_id"]
        ]
        snapshot["competitions"].append(entry)
    rows = sorted(snapshots.values(), key=lambda row: row["snapshot_id"], reverse=True)
    latest = {}
    for snapshot in rows:
        snapshot["competitions"].sort(
            key=lambda row: (
                COMPETITION_IDS.index(row["competition_id"])
                if row["competition_id"] in COMPETITION_IDS
                else len(COMPETITION_IDS),
                row["competition_id"],
            )
        )
        for entry in snapshot["competitions"]:
            latest.setdefault(
                entry["competition_id"],
                {"snapshot_id": snapshot["snapshot_id"], **entry},
            )
    result = {
        "schema_version": 2,
        "updated_at": datetime.now(UTC).isoformat(),
        "namespace": "forecasts",
        "latest_by_competition": latest,
        "snapshots": rows,
    }
    check_publishable(result, policy)
    store.put_json("forecasts/index.json", result)
    if not store.exists("hindcasts/index.json"):
        hindcasts = empty_index("hindcasts")
        check_publishable(hindcasts, policy)
        store.put_json("hindcasts/index.json", hindcasts)
    return result


def stored_documents(store):
    index = store.get_json("forecasts/index.json", empty_index("forecasts"))
    for snapshot in reversed(index["snapshots"]):
        for entry in snapshot["competitions"]:
            yield store.get_json(entry["href"])


def materialize_publication(store, site: Path) -> dict:
    site = Path(site)
    data = site / "data"
    index = store.get_json("forecasts/index.json", empty_index("forecasts"))
    check_publishable(index, load_policy())
    write_json(data / "index.json", index)
    documents = 0
    for snapshot in index["snapshots"]:
        for entry in snapshot["competitions"]:
            document = store.get_json(entry["href"])
            check_publishable(document, load_policy())
            write_json(data / entry["href"], document)
            documents += 1
    record = store.get_json("record.json")
    if record is not None:
        check_publishable(record, load_policy())
        write_json(data / "record.json", record)
    hindcasts = store.get_json("hindcasts/index.json", empty_index("hindcasts"))
    check_publishable(hindcasts, load_policy())
    write_json(data / "hindcasts" / "index.json", hindcasts)
    return {"documents": documents, "record": record is not None}
