"""Retrospective match forecasts that bridge the start of a season to live prospective coverage.

The weekly season hindcasts in `epl_forecast.hindcast` answer a different question: they are
retrospective season-state trajectories of a completed season. These are retrospective match
forecasts of the current season, and they stop where the live prospective record starts, so the
current public model version has match-level coverage from the first matchday.
"""

import os
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, date, datetime, time, timedelta

from epl_forecast.analysis_keys import MATCH_HINDCAST_INDEX_KEY
from epl_forecast.cli import fitted_model
from epl_forecast.competitions import COMPETITION_IDS, competition
from epl_forecast.datasets import Dataset, timestamp
from epl_forecast.hindcast import XG_ASSUMPTION, load_personnel_history, model_config
from epl_forecast.live import LONDON
from epl_forecast.live_forecast import forecast_probability_stages
from epl_forecast.personnel import COMPETITIONS as PERSONNEL_COMPETITIONS
from epl_forecast.personnel import Evidence, fixture_adjustments
from epl_forecast.pipeline import PRODUCT_MODEL, model_code_hashes
from epl_forecast.publication import (
    check_publishable,
    load_policy,
    probability,
    public_personnel,
)
from epl_forecast.storage import json_bytes, sha256_bytes

PREFIX = "match-hindcasts"
INDEX_KEY = MATCH_HINDCAST_INDEX_KEY
MAX_GOALS = 10
ORIGIN_TIME_ZONE = "Europe/London"
ORIGIN_RULE = (
    "Midnight Europe/London on the day of the match. The model uses results and expected goals "
    "that were available before that day, and no result of the day itself."
)
NOTICE = (
    "This is a hindcast. The frozen public model made it after the match was played. "
    "It is not a forecast that existed before the match, and the prospective record does not "
    "include it."
)
# The document key carries this many hex characters of the content digest. A published value of
# 32 or more would read as a leaked source hash, which the publication boundary refuses.
CONTENT_ID_LENGTH = 16
ASSUMPTIONS = (
    "The model uses only the results of matches played before the London day of the match.",
    XG_ASSUMPTION,
    "In the Premier League and the Championship, the match gets the matchday-squad continuity adjustment. The hindcast estimates it from the matchday squads of earlier matches and from dated transfers. It does not use injury lists, squad captures or team sheets, because the data does not show when they were first known.",
    "The model does not use betting markets.",
    "A retrospective match forecast stops before the London day on which live coverage of this model version began. It is never a prospective forecast.",
)


def origin_at(match_date: date) -> datetime:
    """Midnight in London on the day of the match."""
    return datetime.combine(match_date, time.min, tzinfo=LONDON)


def content_id(document: dict) -> str:
    """The identity of one document's content, which names the object that holds it."""
    return sha256_bytes(json_bytes(document))[:CONTENT_ID_LENGTH]


def season_prefix(model_version: str, competition_id: str, season_id: str) -> str:
    return f"{PREFIX}/{model_version}/{competition_id}/{season_id}"


def document_key(model_version: str, competition_id: str, season_id: str, identity: str) -> str:
    """Content addresses the document, so a changed bridge never hides behind a known key.

    The analysis session trusts an object that a mutable pointer selects, and only re-reads when
    the pointer changes. A stable key would let new probabilities arrive under an index entry that
    is unchanged, and a warm session would keep serving the old ones.
    """
    return f"{season_prefix(model_version, competition_id, season_id)}/{identity}.json"


def private_key(model_version: str, competition_id: str, season_id: str, identity: str) -> str:
    return f"runs/{document_key(model_version, competition_id, season_id, identity)}"


def prospective_start(publish_store, model_version: str, competition_id: str) -> date | None:
    """The first London day a live forecast of this model version covered this division.

    The forecast archive of the division is the authority, so no release metadata can drift away
    from what the product actually published. A published forecast only covers kickoffs after it
    was generated, so no prospective row of this version in this division falls before this day.
    Production publishes each division on its own, so one division can reach a version days
    before another, and a division that failed may not have reached it at all.
    """
    archive = publish_store.get_json(f"forecasts/{competition_id}/archive.json")
    days = [
        timestamp(pointer["generated_at"]).astimezone(LONDON).date()
        for pointer in (archive or {}).get("forecasts", ())
        if pointer.get("model_version") == model_version
    ]
    return min(days) if days else None


def boundary(publish_store, model_version: str, competition_id: str) -> dict:
    """The retrospective/prospective handoff of one model version in one division."""
    start = prospective_start(publish_store, model_version, competition_id)
    if start is None:
        raise ValueError(
            f"No published {competition_id} forecast carries model version {model_version}, so "
            "the retrospective bridge of that division has no end. Publish its live forecast "
            "first."
        )
    return {"prospective_from": str(start), "last_match_date": str(start - timedelta(days=1))}


def boundaries(publish_store, model_version: str, competitions) -> dict:
    """The handoff of each division that has live coverage of the version, and nothing else."""
    result = {}
    for competition_id in competitions:
        start = prospective_start(publish_store, model_version, competition_id)
        if start is not None:
            result[competition_id] = {
                "prospective_from": str(start),
                "last_match_date": str(start - timedelta(days=1)),
            }
    return result


def season_of(day: date) -> str:
    year = day.year - (day.month < 7)
    return f"{year}-{year + 1}"


_WORKER = {}


def _initialize(matches, observations, personnel, kickoffs) -> None:
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    _WORKER.update(
        matches=matches, observations=observations, personnel=personnel, kickoffs=kickoffs
    )


def forecast_day(task: dict) -> list[dict]:
    """Every match of one division on one London day, from one fit of the frozen model."""
    matches = _WORKER["matches"]
    kickoffs = _WORKER["kickoffs"]
    as_of = date.fromisoformat(task["match_date"])
    config = model_config(task["competition_id"], _WORKER["observations"])
    model, _, training = fitted_model(matches, config, PRODUCT_MODEL, as_of)
    wanted = set(task["matches"])
    fixtures = [match.fixture for match in matches if match.fixture.match_id in wanted]
    origin = origin_at(as_of)
    records = {}
    if task["competition_id"] in PERSONNEL_COMPETITIONS:
        history = _WORKER["personnel"]
        records = fixture_adjustments(
            Evidence(origin, **history["rows"]),
            defaultdict(list, history["histories"]),
            fixtures,
            kickoffs,
            origin,
        )
    rows = []
    for fixture in sorted(fixtures, key=lambda f: f.match_id):
        record = records.get(fixture.match_id)
        shift = None if record is None else record["home_log_rate_shift"]
        kickoff = kickoffs.get(fixture.match_id)
        stages, _, probabilities, _ = forecast_probability_stages(
            model.predict_match(fixture), MAX_GOALS, shift
        )
        unadjusted = stages["unadjusted"]
        rows.append(
            {
                "match_id": fixture.match_id,
                "match_date": str(fixture.match_date),
                "kickoff_time": None if kickoff is None else kickoff.isoformat(),
                "home_team_id": fixture.home_team_id,
                "away_team_id": fixture.away_team_id,
                "origin_at": origin.isoformat(),
                "model_results_cutoff": str(as_of),
                "training_matches": len(training),
                "p_home": float(probabilities[0]),
                "p_draw": float(probabilities[1]),
                "p_away": float(probabilities[2]),
                "unadjusted": {key: unadjusted[key] for key in ("p_home", "p_draw", "p_away")},
                # The scalar continuity of each club, not the player evidence behind it. The
                # match forecast needs no more, and the private run stays small and printable.
                "personnel": None
                if record is None
                else {
                    side: {
                        field: record[side][field]
                        for field in ("discontinuity", "unresolved_weight")
                    }
                    for side in ("home", "away")
                }
                | {"home_log_rate_shift": shift},
                "score_distribution": stages["personnel_adjusted"]["score_distribution"],
            }
        )
    return rows


# A fixture the calendar places before the handoff, which the canonical history says was not
# played then. It has no retrospective forecast, and the document names it so the gap is visible.
# The canonical status vocabulary is finished, in_progress, postponed and scheduled, and it folds
# a cancelled or abandoned match into postponed, so this is the whole of it.
DEFERRED_STATUSES = ("postponed",)


def scope(fixtures, competition_id: str, season_id: str, handoff: dict) -> tuple[list, list]:
    """Reconcile the calendar before the handoff: what must be forecast, and what was not played.

    `Dataset.matches()` holds finished regular-season matches only, so it proves that every
    forecast has a result but never that every fixture has a forecast. This reads the whole
    regular-season calendar instead and refuses anything it cannot account for.
    """
    last = handoff["last_match_date"]
    in_scope = [
        row
        for row in fixtures
        if (row["competition_id"], row["season_id"], row["stage"])
        == (competition_id, season_id, "regular")
        and row["match_date"] is not None
        and str(row["match_date"]) <= last
    ]
    played = [row for row in in_scope if row["status"] == "finished"]
    deferred = [row for row in in_scope if row["status"] in DEFERRED_STATUSES]
    accounted = ("finished", *DEFERRED_STATUSES)
    unaccounted = [row for row in in_scope if row["status"] not in accounted]
    if unaccounted:
        named = ", ".join(f"{row['match_id']} ({row['status']})" for row in unaccounted[:3])
        raise ValueError(
            f"{len(unaccounted)} {competition_id} {season_id} fixtures on or before {last} have "
            f"no result and no reason: {named}. Collect the results before you make the bridge."
        )
    if not played:
        raise ValueError(f"No {competition_id} {season_id} match was played on or before {last}")
    return played, deferred


def derive_match_hindcast(
    model_version: str,
    competition_id: str,
    season_id: str,
    rows: list[dict],
    handoff: dict,
    deferred: list[dict] = (),
) -> dict:
    """The published document: one retrospective forecast for each match, and no simulation."""
    if not rows:
        raise ValueError(f"No retrospective matches for {competition_id} {season_id}")
    matches = []
    for row in sorted(rows, key=lambda row: (row["match_date"], row["match_id"])):
        if row["match_date"] > handoff["last_match_date"]:
            raise ValueError(
                f"A retrospective match forecast on {row['match_date']} is not before the "
                f"prospective coverage of {model_version}"
            )
        scores = row["score_distribution"]
        matches.append(
            {
                "match_id": row["match_id"],
                "match_date": row["match_date"],
                "kickoff_time": None
                if row["kickoff_time"] is None
                else timestamp(row["kickoff_time"]).isoformat(),
                "home_team_id": row["home_team_id"],
                "away_team_id": row["away_team_id"],
                "origin_at": row["origin_at"],
                "model_results_cutoff": row["model_results_cutoff"],
                "p_home": probability(row["p_home"]),
                "p_draw": probability(row["p_draw"]),
                "p_away": probability(row["p_away"]),
                "unadjusted": {
                    key: probability(row["unadjusted"][key])
                    for key in ("p_home", "p_draw", "p_away")
                },
                "personnel": public_personnel(row["personnel"]),
                "score_probabilities": {
                    "home_rate": round(float(scores["home_rate"]), 6),
                    "away_rate": round(float(scores["away_rate"]), 6),
                    "omitted_probability": probability(scores["omitted_probability"]),
                    "grid_home_rows_away_columns": [
                        [probability(cell) for cell in line]
                        for line in scores["grid_home_rows_away_columns"]
                    ],
                },
            }
        )
    return {
        "schema_version": 1,
        "product": "match_hindcast",
        "retrospective": True,
        "notice": NOTICE,
        "competition_id": competition_id,
        "competition_name": competition(competition_id).name,
        "season_id": season_id,
        "model": {"version": model_version},
        "origin_rule": ORIGIN_RULE,
        "assumptions": list(ASSUMPTIONS),
        "prospective_from": handoff["prospective_from"],
        "last_match_date": matches[-1]["match_date"],
        "deferred_fixtures": [
            {
                "match_id": row["match_id"],
                "match_date": str(row["match_date"]),
                "status": row["status"],
            }
            for row in sorted(deferred, key=lambda row: (str(row["match_date"]), row["match_id"]))
        ],
        "matches": matches,
    }


def index_entry(document: dict) -> dict:
    """The pointer to one division's bridge. Its href holds the content identity of the document,
    so any change to the document changes this entry and every reader of the index sees it."""
    return {
        "model_version": document["model"]["version"],
        "competition_id": document["competition_id"],
        "competition_name": document["competition_name"],
        "season_id": document["season_id"],
        "match_count": len(document["matches"]),
        "deferred_count": len(document["deferred_fixtures"]),
        "first_match_date": document["matches"][0]["match_date"],
        "last_match_date": document["last_match_date"],
        "prospective_from": document["prospective_from"],
        "href": document_key(
            document["model"]["version"],
            document["competition_id"],
            document["season_id"],
            content_id(document),
        ),
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
        "product": "match_hindcast",
        "retrospective": True,
        "notice": NOTICE,
        "updated_at": datetime.now(UTC).isoformat(),
        "seasons": ordered,
    }
    check_publishable(result, policy, "match_hindcast_index")
    publish_store.put_json(INDEX_KEY, result)
    return result


def run_match_hindcasts(
    data_store,
    publish_store,
    competitions=COMPETITION_IDS,
    season_id: str | None = None,
    workers: int = 4,
    log=print,
) -> dict:
    """Forecast every match each division played before live coverage of the model began.

    Each division has its own handoff, because production publishes each division on its own and
    one of them can fail while the others go out. A division that has no live forecast of this
    model version has no handoff, so it gets no bridge and the result says so.
    """
    policy = load_policy()
    model_version = policy["product"]["model_version"]
    handoffs = boundaries(publish_store, model_version, competitions)
    skipped = [competition_id for competition_id in competitions if competition_id not in handoffs]
    if not handoffs:
        raise ValueError(
            f"No published forecast of any division carries model version {model_version}, so "
            "the retrospective bridge has no end. Publish the live forecasts first."
        )
    for competition_id in skipped:
        log(f"Skipping {competition_id}: no live forecast carries {model_version} yet")
    latest = max(date.fromisoformat(h["last_match_date"]) for h in handoffs.values())
    season_id = season_id or season_of(latest)
    data = Dataset(store=data_store)
    try:
        matches = data.matches()
        observations = data.xg_observations()
        fixtures = data.fixtures()
        kickoffs = {row["match_id"]: row["kickoff_time"] for row in fixtures}
        personnel = load_personnel_history(data, (int(season_id[:4]),))
    finally:
        data.close()
    results = {match.fixture.match_id: match for match in matches}
    expected, deferred, targets = {}, {}, defaultdict(list)
    for competition_id, handoff in handoffs.items():
        played, not_played = scope(fixtures, competition_id, season_id, handoff)
        missing = [row["match_id"] for row in played if row["match_id"] not in results]
        if missing:
            raise ValueError(
                f"{len(missing)} finished {competition_id} {season_id} fixtures have no canonical "
                f"result: {', '.join(missing[:3])}"
            )
        expected[competition_id] = {row["match_id"] for row in played}
        deferred[competition_id] = not_played
        for row in played:
            targets[competition_id, str(row["match_date"])].append(row["match_id"])
    tasks = [
        {"competition_id": competition_id, "match_date": day, "matches": sorted(match_ids)}
        for (competition_id, day), match_ids in sorted(targets.items())
    ]
    log(
        f"{sum(len(task['matches']) for task in tasks)} matches on {len(tasks)} division days, "
        f"in {len(handoffs)} divisions"
    )
    rows = defaultdict(list)
    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=_initialize,
        initargs=(matches, observations, personnel, kickoffs),
    ) as pool:
        futures = {pool.submit(forecast_day, task): task for task in tasks}
        for done, future in enumerate(as_completed(futures), 1):
            task = futures[future]
            rows[task["competition_id"]].extend(future.result())
            log(f"[{done}/{len(tasks)}] {task['competition_id']} {task['match_date']}")
    entries = []
    for competition_id, handoff in handoffs.items():
        forecast = {row["match_id"] for row in rows[competition_id]}
        if forecast != expected[competition_id]:
            gap = sorted(expected[competition_id] - forecast) or sorted(
                forecast - expected[competition_id]
            )
            raise ValueError(
                f"The {competition_id} bridge covers {len(forecast)} of "
                f"{len(expected[competition_id])} matches: {', '.join(gap[:3])}"
            )
        document = derive_match_hindcast(
            model_version,
            competition_id,
            season_id,
            rows[competition_id],
            handoff,
            deferred[competition_id],
        )
        check_publishable(document, policy, "match_hindcast")
        identity = content_id(document)
        # The private run first, then the sanitized public document, both immutable at a key that
        # the content names. A regenerated bridge writes new objects and moves the index.
        data_store.put_json(
            private_key(model_version, competition_id, season_id, identity),
            {
                "schema_version": 1,
                "model_version": model_version,
                "model_id": PRODUCT_MODEL,
                "model_code": model_code_hashes(),
                "competition_id": competition_id,
                "season_id": season_id,
                "max_goals": MAX_GOALS,
                "origin_rule": ORIGIN_RULE,
                **handoff,
                "matches": sorted(rows[competition_id], key=lambda row: row["match_id"]),
            },
            immutable=True,
        )
        key = document_key(model_version, competition_id, season_id, identity)
        publish_store.put_json(key, document, immutable=True)
        entries.append(index_entry(document))
        log(f"Published {key} ({len(document['matches'])} matches)")
    publish_index(publish_store, entries, policy)
    return {
        "model_version": model_version,
        "season_id": season_id,
        "handoffs": {c: h["prospective_from"] for c, h in handoffs.items()},
        "skipped": skipped,
        "divisions": len(entries),
        "matches": sum(entry["match_count"] for entry in entries),
        "deferred": sum(entry["deferred_count"] for entry in entries),
    }
