"""Prospective scoring over the published forecast archive.

The ledger reads only published documents and realized results, so it can be
rebuilt at any time without touching the forecasts themselves. A match is scored
once, against the last snapshot generated before its kickoff, and season
snapshots are listed as pending until their season settles.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from epl_forecast.evaluation import metrics
from epl_forecast.publication import (
    check_publishable,
    last_pre_kickoff,
    published_documents,
    write_derived,
)


def realized_outcomes(fixtures) -> dict:
    settled = {}
    for row in fixtures:
        if row["status"] != "finished" or row["home_goals"] is None or row["away_goals"] is None:
            continue
        home, away = int(row["home_goals"]), int(row["away_goals"])
        settled[row["match_id"]] = "H" if home > away else "A" if away > home else "D"
    return settled


def pre_kickoff_forecasts(site: Path) -> dict:
    """The last H/D/A forecast published for each match before that match kicked off."""

    def extract(document):
        for match in document["matches"]:
            yield (
                match["match_id"],
                match["kickoff_time"],
                {
                    "match_id": match["match_id"],
                    "competition_id": document["competition_id"],
                    "season_id": document["season_id"],
                    "kickoff_time": match["kickoff_time"],
                    "p_home": match["p_home"],
                    "p_draw": match["p_draw"],
                    "p_away": match["p_away"],
                },
            )

    return last_pre_kickoff(site, extract)


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


def build_ledger(site: Path, outcomes: dict, policy: dict) -> dict:
    return build_record(site, outcomes, policy, "ledger.json")


def build_record(site: Path, outcomes: dict, policy: dict, filename: str = "record.json") -> dict:
    forecasts = pre_kickoff_forecasts(site)
    settled, unsettled = [], 0
    for match_id, row in sorted(forecasts.items()):
        if match_id not in outcomes:
            unsettled += 1
            continue
        settled.append({**row, "outcome": outcomes[match_id]})
    summary = {}
    if settled:
        summary["overall"] = _summary(settled)
        for competition in sorted({row["competition_id"] for row in settled}):
            rows = [row for row in settled if row["competition_id"] == competition]
            summary[competition] = _summary(rows)
    pending = sorted(
        {
            (document["competition_id"], document["season_id"], document["snapshot_id"])
            for document in published_documents(site)
        }
    )
    record = {
        "schema_version": 1,
        "archived_at": datetime.now(UTC).isoformat(),
        "unsettled": unsettled,
        "summary": summary,
        "settled": sorted(settled, key=lambda row: (row["kickoff_time"], row["match_id"])),
        "pending_season_snapshots": [
            {"competition_id": competition, "season_id": season, "snapshot_id": snapshot}
            for competition, season, snapshot in pending
        ],
    }
    check_publishable(record, policy)
    return write_derived(Path(site) / "data" / filename, record)


def read_ledger(site: Path) -> dict:
    path = Path(site) / "data" / "ledger.json"
    return json.loads(path.read_text()) if path.exists() else {}
