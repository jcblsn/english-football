"""Retrospective weekly hindcasts of completed seasons, made with the frozen structural model."""

import os
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, date, datetime, time, timedelta

from epl_forecast.cli import fitted_model, load_config
from epl_forecast.competitions import COMPETITION_IDS, competition
from epl_forecast.datasets import Dataset
from epl_forecast.live import LONDON
from epl_forecast.personnel import COMPETITIONS as PERSONNEL_COMPETITIONS
from epl_forecast.personnel import (
    Evidence,
    club_histories,
    dated_history,
    fixture_adjustments,
    load_evidence,
)
from epl_forecast.pipeline import PRODUCT_CONFIG, PRODUCT_MODEL, model_code_hashes
from epl_forecast.publication import (
    MINIMUM_SIMULATIONS,
    check_publishable,
    load_policy,
    season_team_rows,
)
from epl_forecast.sanctions import load_registry
from epl_forecast.simulation import simulate_season

PREFIX = "hindcasts"
INDEX_KEY = f"{PREFIX}/index.json"
SEED = 20260905
SEASONS = tuple(range(2021, 2026))
ORIGIN_TIME = time(9)
# Wednesday. The weekday of the origin is an observation protocol: it decides when a
# retrospective forecast is taken, not how the model forecasts. Changing it does not make
# the model better or worse, and the edition records it so a reader need not read the code.
ORIGIN_WEEKDAY = 2
ORIGIN_WEEKDAY_NAME = "Wednesday"
ORIGIN_TIME_ZONE = "Europe/London"
ORIGIN_RULE = f"Each {ORIGIN_WEEKDAY_NAME} at 09:00 {ORIGIN_TIME_ZONE}, from the {ORIGIN_WEEKDAY_NAME} on or before the first regular-season match to the first {ORIGIN_WEEKDAY_NAME} after the last result."
SERIES_FIELDS = (
    "played",
    "current_points",
    "mean_points",
    "median_points",
    "mean_position",
    "median_position",
    "position_sd",
    "mean_goal_difference",
)
NOTICE = (
    "This is a hindcast. The frozen public model made it after the season was complete. "
    "It is not a forecast that existed at the origin time, and the prospective record does not include it."
)
ASSUMPTIONS = (
    "The model uses only the results of matches played before the London day of the origin.",
    "In the Premier League, the model also uses expected goals. It assumes that the expected goals of a match were available on the day after the match. The data does not show when they were first available.",
    "The simulation uses the dates on which the remaining matches were finally played. At the origin time, some of these dates were not known.",
    "A points deduction applies only from its reviewed announcement date.",
    "The division rules, promotion places and playoff format are those of the season.",
    "In the Premier League and the Championship, a match in the six days after the origin gets the matchday-squad continuity adjustment. The hindcast estimates it from the matchday squads of earlier matches and from dated transfers. It does not use injury lists, squad captures or team sheets, because the data does not show when they were first known.",
    "The model does not use betting markets.",
)


def hindcast_id(origin: datetime) -> str:
    return origin.astimezone(UTC).strftime("%Y-%m-%dT%H%M%SZ")


def weekly_origins(
    first_match: date,
    last_match: date,
    weekday: int = ORIGIN_WEEKDAY,
    at: time = ORIGIN_TIME,
) -> list[datetime]:
    """Every `weekday` at `at` in London, from before the first match until every result is known.

    The origins are London wall-clock times, so an origin keeps its local hour across a
    daylight-saving change and its UTC instant moves instead.
    """
    day = first_match - timedelta(days=(first_match.weekday() - weekday) % 7)
    final = last_match + timedelta(days=1)
    final += timedelta(days=(weekday - final.weekday()) % 7)
    origins = []
    while day <= final:
        origins.append(datetime.combine(day, at, tzinfo=LONDON))
        day += timedelta(days=7)
    return origins


def season_prefix(model_version: str, competition_id: str, season_id: str) -> str:
    return f"{PREFIX}/{model_version}/{competition_id}/{season_id}"


def document_key(task: dict) -> str:
    prefix = season_prefix(task["model_version"], task["competition_id"], task["season_id"])
    return f"{prefix}/{task['hindcast_id']}.json"


def private_key(task: dict) -> str:
    return f"runs/{document_key(task)}"


def season_matches(matches, competition_id: str, season_id: str) -> list:
    rows = sorted(
        (
            m
            for m in matches
            if (m.fixture.competition_id, m.fixture.season_id) == (competition_id, season_id)
        ),
        key=lambda m: (m.fixture.match_date, m.fixture.match_id),
    )
    expected = competition(competition_id).matches
    if len(rows) != expected or len({m.fixture.match_id for m in rows}) != expected:
        raise ValueError(
            f"{competition_id} {season_id} is not a complete season: {len(rows)} of {expected} results"
        )
    return rows


def table_at(teams: list[str], played: list, adjustments: list[dict]) -> dict[str, dict]:
    table = {team: {"played": 0, "current_points": 0} for team in teams}
    for match in played:
        home, away = table[match.fixture.home_team_id], table[match.fixture.away_team_id]
        home["played"] += 1
        away["played"] += 1
        home["current_points"] += 3 if match.outcome == "H" else int(match.outcome == "D")
        away["current_points"] += 3 if match.outcome == "A" else int(match.outcome == "D")
    for adjustment in adjustments:
        table[adjustment["team_id"]]["current_points"] += adjustment["points"]
    return table


def model_config(competition_id: str, observations: list[dict]) -> dict:
    """The product configuration, with xG read once from the R2 history for every origin."""
    config = load_config(PRODUCT_CONFIG)
    config["competition_id"] = competition_id
    for spec in config["models"]:
        parameters = spec.setdefault("parameters", {})
        parameters["competition_id"] = competition_id
        if parameters.pop("canonical_xg", False):
            parameters["observations"] = observations
    return config


def edition(model_version: str, simulations: int) -> dict:
    return {
        "schema_version": 1,
        "model_version": model_version,
        "model_id": PRODUCT_MODEL,
        "model_code": model_code_hashes(),
        "simulations": simulations,
        "seed": SEED,
        "origin_rule": ORIGIN_RULE,
        "origin_weekday": ORIGIN_WEEKDAY_NAME,
        "origin_time": ORIGIN_TIME.isoformat(),
        "origin_time_zone": ORIGIN_TIME_ZONE,
    }


def claim_edition(data_store, manifest: dict) -> None:
    """One public model version has one frozen model, so its hindcasts never mix two models."""
    key = f"runs/{PREFIX}/{manifest['model_version']}/edition.json"
    existing = data_store.get_json(key)
    if existing is None:
        data_store.put_json(key, manifest, immutable=True)
    elif existing != manifest:
        raise ValueError(
            f"The {manifest['model_version']} hindcasts used a different model or settings. "
            "Change the public model version before you make new hindcasts."
        )


_WORKER = {}


def _initialize(matches, observations, personnel) -> None:
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    _WORKER.update(matches=matches, observations=observations, personnel=personnel)


def load_personnel_history(data, seasons) -> dict:
    """Matchday squads and transfers dated by history, for the divisions with the adjustment."""
    fixtures = [row for row in data.fixtures() if row["competition_id"] in PERSONNEL_COMPETITIONS]
    in_scope = {row["match_id"] for row in fixtures}
    identifiers = sorted(
        {f"{year - 1}-{year}" for year in seasons} | {f"{y}-{y + 1}" for y in seasons}
    )
    rows = load_evidence(data, identifiers)
    appearances = [row for row in rows["appearances"] if row["match_id"] in in_scope]
    return {
        "rows": dated_history(appearances, rows["transfers"]),
        "histories": dict(club_histories(fixtures)),
        "kickoffs": {row["match_id"]: row["kickoff_time"] for row in fixtures},
    }


def simulate_origin(task: dict) -> dict:
    matches = _WORKER["matches"]
    config = model_config(task["competition_id"], _WORKER["observations"])
    as_of = date.fromisoformat(task["model_results_cutoff"])
    model, _, training = fitted_model(matches, config, PRODUCT_MODEL, as_of)
    season = season_matches(matches, task["competition_id"], task["season_id"])
    played = [m for m in season if m.available_on <= as_of]
    remaining = [m.fixture for m in season if m.available_on > as_of]
    teams = sorted({t for m in season for t in (m.fixture.home_team_id, m.fixture.away_team_id)})
    shifts = {}
    if task["competition_id"] in PERSONNEL_COMPETITIONS:
        history = _WORKER["personnel"]
        origin = datetime.fromisoformat(task["origin_at"])
        records = fixture_adjustments(
            Evidence(origin, **history["rows"]),
            defaultdict(list, history["histories"]),
            remaining,
            history["kickoffs"],
            origin,
        )
        shifts = {
            match_id: record["home_log_rate_shift"]
            for match_id, record in records.items()
            if record["home_log_rate_shift"] is not None
        }
    simulation = simulate_season(
        model,
        played,
        remaining,
        teams,
        as_of,
        task["simulations"],
        task["seed"],
        task["adjustments"],
        log_rate_shifts=shifts,
    )
    table = table_at(teams, played, task["adjustments"])
    for row in simulation["teams"]:
        row.pop("goal_difference_distribution")
        row.update(table[row["team_id"]])
    simulation.pop("match_frequencies")
    return {
        **task,
        "training_matches": len(training),
        "personnel_adjusted_fixtures": len(shifts),
        "simulation": simulation,
    }


def derive_hindcast(record: dict, names: dict) -> dict:
    simulation = record["simulation"]
    if simulation["simulations"] < MINIMUM_SIMULATIONS:
        raise ValueError(
            f"Refusing to publish {simulation['simulations']} simulated paths; the product floor is {MINIMUM_SIMULATIONS}"
        )
    return {
        "schema_version": 1,
        "product": "hindcast",
        "retrospective": True,
        "notice": NOTICE,
        "hindcast_id": record["hindcast_id"],
        "competition_id": record["competition_id"],
        "competition_name": competition(record["competition_id"]).name,
        "season_id": record["season_id"],
        "origin_at": record["origin_at"],
        "model_results_cutoff": record["model_results_cutoff"],
        "played_matches": simulation["played_matches"],
        "remaining_matches": simulation["remaining_matches"],
        "simulations": simulation["simulations"],
        "state_uncertainty": simulation["state_uncertainty"],
        "model": {"version": record["model_version"]},
        "assumptions": list(ASSUMPTIONS),
        "teams": season_team_rows(simulation["teams"], names),
    }


def derive_series(documents: list[dict]) -> dict:
    """Weekly arrays for each club, aligned with the origins, so a reader needs no model state."""
    documents = sorted(documents, key=lambda document: document["hindcast_id"])
    first, last = documents[0], documents[-1]
    identity = {
        (d["competition_id"], d["season_id"], d["model"]["version"], d["simulations"])
        for d in documents
    }
    clubs = {frozenset(row["team_id"] for row in d["teams"]) for d in documents}
    if len(identity) != 1 or len(clubs) != 1:
        raise ValueError("A hindcast series needs one division, season, model and club list")
    by_team = [{row["team_id"]: row for row in d["teams"]} for d in documents]
    teams = []
    for team in last["teams"]:
        rows = [rows_by_team[team["team_id"]] for rows_by_team in by_team]
        events = sorted({event for row in rows for event in row["events"]})
        teams.append(
            {
                "team_id": team["team_id"],
                "name": team["name"],
                **{field: [row[field] for row in rows] for field in SERIES_FIELDS},
                **{
                    field: {level: [row[field][level] for row in rows] for level in rows[0][field]}
                    for field in ("points_intervals", "position_intervals")
                },
                "events": {event: [row["events"].get(event) for row in rows] for event in events},
            }
        )
    prefix = season_prefix(first["model"]["version"], first["competition_id"], first["season_id"])
    return {
        "schema_version": 1,
        "product": "hindcast",
        "retrospective": True,
        "notice": NOTICE,
        "competition_id": first["competition_id"],
        "competition_name": first["competition_name"],
        "season_id": first["season_id"],
        "model": {"version": first["model"]["version"]},
        "simulations": first["simulations"],
        "assumptions": first["assumptions"],
        "origins": [
            {
                "hindcast_id": d["hindcast_id"],
                "origin_at": d["origin_at"],
                "model_results_cutoff": d["model_results_cutoff"],
                "played_matches": d["played_matches"],
                "href": f"{prefix}/{d['hindcast_id']}.json",
            }
            for d in documents
        ],
        "teams": teams,
    }


def publish_origin(record: dict, names: dict, policy: dict, data_store, publish_store) -> dict:
    """Keep the private run first, then write the sanitized, immutable public document."""
    data_store.put_json(private_key(record), record, immutable=True)
    document = derive_hindcast(record, names)
    check_publishable(document, policy, "hindcast")
    publish_store.put_json(document_key(record), document, immutable=True)
    return document


def publish_season(publish_store, plan: list[dict], policy: dict) -> dict:
    documents = [publish_store.get_json(document_key(task)) for task in plan]
    if any(document is None for document in documents):
        raise ValueError("Every weekly hindcast of a season must exist before its series")
    series = derive_series(documents)
    check_publishable(series, policy, "hindcast_series")
    key = f"{season_prefix(plan[0]['model_version'], plan[0]['competition_id'], plan[0]['season_id'])}/series.json"
    if publish_store.get_json(key) != series:
        publish_store.put_json(key, series)
    return {
        "model_version": series["model"]["version"],
        "competition_id": series["competition_id"],
        "competition_name": series["competition_name"],
        "season_id": series["season_id"],
        "origin_count": len(series["origins"]),
        "first_origin_at": series["origins"][0]["origin_at"],
        "last_origin_at": series["origins"][-1]["origin_at"],
        "href": key,
    }


def publish_index(publish_store, entries: list[dict], policy: dict) -> dict:
    index = publish_store.get_json(INDEX_KEY) or {"seasons": []}
    rows = {(r["model_version"], r["competition_id"], r["season_id"]): r for r in index["seasons"]}
    rows.update({(r["model_version"], r["competition_id"], r["season_id"]): r for r in entries})
    ordered = sorted(
        rows.values(),
        key=lambda r: (
            r["model_version"],
            COMPETITION_IDS.index(r["competition_id"]),
            r["season_id"],
        ),
    )
    if ordered == index["seasons"]:
        return index
    result = {
        "schema_version": 1,
        "product": "hindcast",
        "retrospective": True,
        "notice": NOTICE,
        "updated_at": datetime.now(UTC).isoformat(),
        "seasons": ordered,
    }
    check_publishable(result, policy, "hindcast_index")
    publish_store.put_json(INDEX_KEY, result)
    return result


def run_hindcasts(
    data_store,
    publish_store,
    competitions=COMPETITION_IDS,
    seasons=SEASONS,
    simulations: int = 10000,
    workers: int = 4,
    log=print,
) -> dict:
    """Make every missing weekly hindcast, then the season series and the index. A rerun resumes."""
    if simulations < MINIMUM_SIMULATIONS:
        raise ValueError(f"Hindcasts need at least {MINIMUM_SIMULATIONS} simulated paths")
    policy = load_policy()
    model_version = policy["product"]["model_version"]
    claim_edition(data_store, edition(model_version, simulations))
    data = Dataset(store=data_store)
    try:
        matches = data.matches()
        observations = data.xg_observations()
        sanctions = load_registry(data)
        names = {r["team_id"]: r["name"] for r in data.rows("SELECT * FROM teams")}
        personnel = load_personnel_history(data, seasons)
    finally:
        data.close()
    plans, tasks, recovered = {}, [], []
    for competition_id in competitions:
        for year in seasons:
            season_id = f"{year}-{year + 1}"
            season = season_matches(matches, competition_id, season_id)
            prefix = season_prefix(model_version, competition_id, season_id)
            published = set(publish_store.keys(f"{prefix}/"))
            archived = set(data_store.keys(f"runs/{prefix}/"))
            plan = []
            for origin in weekly_origins(
                season[0].fixture.match_date, season[-1].fixture.match_date
            ):
                as_of = origin.date()
                task = {
                    "model_version": model_version,
                    "competition_id": competition_id,
                    "season_id": season_id,
                    "hindcast_id": hindcast_id(origin),
                    "origin_at": origin.isoformat(),
                    "model_results_cutoff": str(as_of),
                    "simulations": simulations,
                    "seed": SEED,
                    "adjustments": sanctions.known_adjustments(competition_id, season_id, as_of),
                }
                plan.append(task)
                if document_key(task) in published:
                    continue
                (recovered if private_key(task) in archived else tasks).append(task)
            plans[competition_id, season_id] = plan
    log(f"{sum(map(len, plans.values()))} weekly origins; {len(tasks)} to simulate")
    for task in recovered:
        publish_origin(
            data_store.get_json(private_key(task)), names, policy, data_store, publish_store
        )
    waiting = defaultdict(int)
    for task in tasks:
        waiting[task["competition_id"], task["season_id"]] += 1
    entries, failures = [], []

    def finish(season_key) -> None:
        entry = publish_season(publish_store, plans[season_key], policy)
        entries.append(entry)
        publish_index(publish_store, entries, policy)
        log(f"Published {entry['href']} ({entry['origin_count']} origins)")

    for season_key in plans:
        if not waiting[season_key]:
            finish(season_key)
    if tasks:
        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=_initialize,
            initargs=(matches, observations, personnel),
        ) as pool:
            futures = {pool.submit(simulate_origin, task): task for task in tasks}
            for done, future in enumerate(as_completed(futures), 1):
                task = futures[future]
                season_key = task["competition_id"], task["season_id"]
                try:
                    publish_origin(future.result(), names, policy, data_store, publish_store)
                except Exception as error:
                    failures.append(
                        {
                            **{k: task[k] for k in ("competition_id", "season_id", "hindcast_id")},
                            "error": str(error),
                        }
                    )
                    log(f"Failed {document_key(task)}: {error}")
                    continue
                log(f"[{done}/{len(tasks)}] {document_key(task)}")
                waiting[season_key] -= 1
                if not waiting[season_key]:
                    finish(season_key)
    if failures:
        raise RuntimeError(f"{len(failures)} hindcasts failed; run again to resume: {failures[:3]}")
    return {
        "model_version": model_version,
        "origins": sum(map(len, plans.values())),
        "simulated": len(tasks),
        "recovered": len(recovered),
        "seasons": len(entries),
    }
