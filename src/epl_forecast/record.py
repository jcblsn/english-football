"""Update the prospective performance record from compact match candidates."""

from datetime import UTC, datetime

from epl_forecast.datasets import timestamp
from epl_forecast.evaluation import metrics
from epl_forecast.publication import archive_documents, check_publishable


def realized_outcomes(fixtures) -> dict:
    settled = {}
    for row in fixtures:
        if row["status"] != "finished" or row["home_goals"] is None or row["away_goals"] is None:
            continue
        home, away = int(row["home_goals"]), int(row["away_goals"])
        settled[row["match_id"]] = "H" if home > away else "A" if away > home else "D"
    return settled


def empty_record(updated_at: str | None = None) -> dict:
    return {
        "schema_version": 2,
        "updated_at": updated_at or datetime.now(UTC).isoformat(),
        "unsettled": 0,
        "summary": {},
        "settled": [],
        "pending": [],
    }


def _renormalize(row: dict) -> dict:
    total = row["p_home"] + row["p_draw"] + row["p_away"]
    return {**row, **{key: row[key] / total for key in ("p_home", "p_draw", "p_away")}}


def _summary(rows: list[dict]) -> dict:
    scored = metrics([_renormalize(row) for row in rows])[0]
    return {
        "scored": scored["matches"],
        "log_loss": round(scored["log_loss"], 6),
        "brier": round(scored["brier"], 6),
        "classwise_ece": round(scored["classwise_ece"], 6),
    }


def update_record(
    record: dict | None,
    documents: list[dict],
    outcomes: dict,
    policy: dict,
    updated_at: str | None = None,
) -> dict:
    if not record or record.get("schema_version") != 2:
        record = empty_record(updated_at)
    pending = {row["match_id"]: row for row in record["pending"]}
    settled = {row["match_id"]: row for row in record["settled"]}
    for document in documents:
        if document.get("retrospective") or document.get("product") == "hindcast":
            raise ValueError("A hindcast cannot enter the prospective record")
        generated = timestamp(document["generated_at"])
        for match in document["matches"]:
            if not match["kickoff_time"] or generated >= timestamp(match["kickoff_time"]):
                continue
            candidate = {
                "match_id": match["match_id"],
                "competition_id": document["competition_id"],
                "season_id": document["season_id"],
                "kickoff_time": match["kickoff_time"],
                "forecast_id": document["forecast_id"],
                "generated_at": document["generated_at"],
                "model_version": document["model"]["version"],
                "p_home": match["p_home"],
                "p_draw": match["p_draw"],
                "p_away": match["p_away"],
            }
            current = pending.get(match["match_id"])
            if not current or timestamp(current["generated_at"]) < generated:
                pending[match["match_id"]] = candidate
    for match_id, outcome in outcomes.items():
        candidate = pending.pop(match_id, None)
        if candidate:
            settled[match_id] = {**candidate, "outcome": outcome}
        elif match_id in settled:
            settled[match_id]["outcome"] = outcome
    rows = sorted(settled.values(), key=lambda row: (row["kickoff_time"], row["match_id"]))
    summary = {}
    if rows:
        summary["overall"] = _summary(rows)
        for competition_id in sorted({row["competition_id"] for row in rows}):
            summary[competition_id] = _summary(
                [row for row in rows if row["competition_id"] == competition_id]
            )
    result = {
        "schema_version": 2,
        "updated_at": updated_at or datetime.now(UTC).isoformat(),
        "unsettled": len(pending),
        "summary": summary,
        "settled": rows,
        "pending": sorted(pending.values(), key=lambda row: (row["kickoff_time"], row["match_id"])),
    }
    check_publishable(result, policy, "record")
    return result


def rebuild_record(store, outcomes: dict, policy: dict) -> dict:
    current = store.get_json("forecasts/current.json", {"forecasts": []})
    documents = [
        document
        for entry in current["forecasts"]
        for document in archive_documents(store, entry["competition_id"])
    ]
    return update_record(None, documents, outcomes, policy)
