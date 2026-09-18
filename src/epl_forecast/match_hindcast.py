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
from epl_forecast.hindcast import load_personnel_history, model_config
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
ASSUMPTIONS = (
    "The model uses only the results of matches played before the London day of the match.",
    "In the Premier League, the model also uses expected goals. It assumes that the expected goals of a match were available on the day after the match. The data does not show when they were first available.",
    "In the Premier League and the Championship, the match gets the matchday-squad continuity adjustment. The hindcast estimates it from the matchday squads of earlier matches and from dated transfers. It does not use injury lists, squad captures or team sheets, because the data does not show when they were first known.",
    "The model does not use betting markets.",
    "A retrospective match forecast stops before the London day on which live coverage of this model version began. It is never a prospective forecast.",
)


def origin_at(match_date: date) -> datetime:
    """Midnight in London on the day of the match."""
    return datetime.combine(match_date, time.min, tzinfo=LONDON)


def document_key(model_version: str, competition_id: str, season_id: str) -> str:
    return f"{PREFIX}/{model_version}/{competition_id}/{season_id}.json"


def private_key(model_version: str, competition_id: str, season_id: str) -> str:
    return f"runs/{document_key(model_version, competition_id, season_id)}"


def prospective_start(publish_store, model_version: str) -> date | None:
    """The first London day on which a live forecast of this model version was published.

    The forecast archives are the authority, so no release metadata can drift away from what
    the product actually published. A published forecast only covers kickoffs after it was
    generated, so no prospective row of this version can fall before this day.
    """
    days = []
    for competition_id in COMPETITION_IDS:
        archive = publish_store.get_json(f"forecasts/{competition_id}/archive.json")
        days.extend(
            timestamp(pointer["generated_at"]).astimezone(LONDON).date()
            for pointer in (archive or {}).get("forecasts", ())
            if pointer.get("model_version") == model_version
        )
    return min(days) if days else None


def boundary(publish_store, model_version: str) -> dict:
    """The retrospective/prospective handoff of one model version."""
    start = prospective_start(publish_store, model_version)
    if start is None:
        raise ValueError(
            f"No published forecast carries model version {model_version}, so the retrospective "
            "bridge has no end. Publish the live forecasts first."
        )
    return {"prospective_from": str(start), "last_match_date": str(start - timedelta(days=1))}


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
        stages, _, probabilities, _ = forecast_probability_stages(
            model.predict_match(fixture), MAX_GOALS, shift
        )
        unadjusted = stages["unadjusted"]
        rows.append(
            {
                "match_id": fixture.match_id,
                "match_date": str(fixture.match_date),
                "kickoff_time": kickoffs[fixture.match_id],
                "home_team_id": fixture.home_team_id,
                "away_team_id": fixture.away_team_id,
                "origin_at": origin.isoformat(),
                "model_results_cutoff": str(as_of),
                "training_matches": len(training),
                "p_home": float(probabilities[0]),
                "p_draw": float(probabilities[1]),
                "p_away": float(probabilities[2]),
                "unadjusted": {key: unadjusted[key] for key in ("p_home", "p_draw", "p_away")},
                "personnel": record,
                "score_distribution": stages["personnel_adjusted"]["score_distribution"],
            }
        )
    return rows


def derive_match_hindcast(
    model_version: str,
    competition_id: str,
    season_id: str,
    rows: list[dict],
    handoff: dict,
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
        "matches": matches,
    }


def index_entry(document: dict) -> dict:
    return {
        "model_version": document["model"]["version"],
        "competition_id": document["competition_id"],
        "competition_name": document["competition_name"],
        "season_id": document["season_id"],
        "match_count": len(document["matches"]),
        "first_match_date": document["matches"][0]["match_date"],
        "last_match_date": document["last_match_date"],
        "prospective_from": document["prospective_from"],
        "href": document_key(
            document["model"]["version"], document["competition_id"], document["season_id"]
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
    """Forecast every finished match of the season before live coverage of the model began."""
    policy = load_policy()
    model_version = policy["product"]["model_version"]
    handoff = boundary(publish_store, model_version)
    last = date.fromisoformat(handoff["last_match_date"])
    season_id = season_id or season_of(last)
    data = Dataset(store=data_store)
    try:
        matches = data.matches()
        observations = data.xg_observations()
        kickoffs = {row["match_id"]: row["kickoff_time"] for row in data.fixtures()}
        personnel = load_personnel_history(data, (int(season_id[:4]),))
    finally:
        data.close()
    targets = defaultdict(list)
    for match in matches:
        fixture = match.fixture
        if fixture.competition_id not in competitions or fixture.season_id != season_id:
            continue
        if fixture.match_date > last:
            continue
        targets[fixture.competition_id, str(fixture.match_date)].append(fixture.match_id)
    if not targets:
        raise ValueError(f"No finished {season_id} matches before {handoff['prospective_from']}")
    tasks = [
        {"competition_id": competition_id, "match_date": day, "matches": sorted(match_ids)}
        for (competition_id, day), match_ids in sorted(targets.items())
    ]
    log(
        f"{sum(len(task['matches']) for task in tasks)} matches on {len(tasks)} division days "
        f"before {handoff['prospective_from']}"
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
    for competition_id in competitions:
        if not rows[competition_id]:
            continue
        document = derive_match_hindcast(
            model_version, competition_id, season_id, rows[competition_id], handoff
        )
        check_publishable(document, policy, "match_hindcast")
        data_store.put_json(
            private_key(model_version, competition_id, season_id),
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
        )
        key = document_key(model_version, competition_id, season_id)
        if publish_store.get_json(key) != document:
            publish_store.put_json(key, document)
        entries.append(index_entry(document))
        log(f"Published {key} ({len(document['matches'])} matches)")
    publish_index(publish_store, entries, policy)
    return {
        "model_version": model_version,
        "season_id": season_id,
        **handoff,
        "divisions": len(entries),
        "matches": sum(entry["match_count"] for entry in entries),
    }
