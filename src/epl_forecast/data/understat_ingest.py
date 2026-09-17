"""Understat league and player process observations, reconciled to canonical fixtures."""

import gzip
import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from epl_forecast.data.api_football import team_registry
from epl_forecast.datasets import Dataset, publish, timestamp
from epl_forecast.schema import fixture_id


def name_tokens(value):
    return " ".join(
        re.findall(
            "[a-z]+",
            unicodedata.normalize("NFKD", value.lower()).encode("ascii", "ignore").decode(),
        )
    )


class IngestContext:
    """Canonical reads reused across a run of Understat player-match ingests.

    Each ingest needs the schedule, every retained Understat-to-canonical link and
    the retained names, all filtered to what was observed by the payload's own
    retrieval time. Reading the whole store once per match dominated a bulk
    publication, so the reads happen once and the identities each ingest publishes
    are folded back in, which is the only part that changes as the run proceeds.
    """

    def __init__(self, root):
        data = Dataset(workspace=root)
        try:
            self.fixtures = {r["match_id"]: r for r in data.fixtures()}
            self.links = [
                (r["understat_id"], r["player_id"], timestamp(r["retrieved_at"]))
                for r in data.rows(
                    "SELECT DISTINCT understat_id, player_id, retrieved_at "
                    "FROM players_observations WHERE understat_id IS NOT NULL"
                )
            ]
            self.names = defaultdict(list)
            for r in data.rows(
                "SELECT DISTINCT player_id, name, retrieved_at FROM players_observations "
                "WHERE name IS NOT NULL"
            ):
                self.names[r["player_id"]].append((r["name"], timestamp(r["retrieved_at"])))
            self.appearances = defaultdict(list)
            for r in data.rows(
                "SELECT DISTINCT match_id, team_id, player_id, retrieved_at "
                "FROM appearances_observations"
            ):
                self.appearances[r["match_id"]].append(
                    (r["team_id"], r["player_id"], timestamp(r["retrieved_at"]))
                )
        finally:
            data.close()

    def known_links(self, retrieved_at):
        known = {}
        for understat_id, player, observed in self.links:
            if observed > retrieved_at:
                continue
            if understat_id in known and known[understat_id] != player:
                raise ValueError(f"Contradictory retained player mapping: Understat {understat_id}")
            known[understat_id] = player
        return known

    def match_appearances(self, match_id, retrieved_at):
        rows = []
        for team, player, observed in self.appearances.get(match_id, ()):
            if observed > retrieved_at:
                continue
            for name, named_at in self.names.get(player, ()):
                if named_at <= retrieved_at:
                    rows.append({"team_id": team, "player_id": player, "name": name})
        return rows

    def record(self, identities, retrieved_at):
        for identity in identities:
            self.links.append((identity["understat_id"], identity["player_id"], retrieved_at))
            self.names[identity["player_id"]].append((identity["name"], retrieved_at))


def ingest(root, record, payload, context=None):
    body = json.loads(gzip.decompress(payload) if payload.startswith(b"\x1f\x8b") else payload)
    request = record["context"]
    data = None if context is not None and request["kind"] == "players" else Dataset(workspace=root)
    try:
        fixtures = context.fixtures if data is None else {r["match_id"]: r for r in data.fixtures()}
        if request["kind"] == "league":
            year = request["season_start"]
            season, comp = f"{year}-{year + 1}", "eng-premier-league"
            aliases = team_registry()
            aliases.update(
                {
                    "Newcastle United": "newcastle-united",
                    "West Bromwich Albion": "west-bromwich-albion",
                }
            )
            corrections = {
                r["source_match_id"]: r
                for r in json.loads(
                    Path(__file__).with_name("understat_date_corrections.json").read_text()
                )
            }
            rows = []
            for r in body["dates"]:
                if not r.get("isResult"):
                    continue
                h, a = (aliases[r[side]["title"]] for side in ("h", "a"))
                key = fixture_id(comp, season, h, a)
                f = fixtures.get(key)
                if f is None:
                    raise ValueError(f"Understat fixture not in canonical schedule: {key}")
                if datetime.fromisoformat(r["datetime"]).date() != f["match_date"]:
                    correction = corrections.get(str(r["id"]), {})
                    if (
                        correction.get("match_id") != key
                        or correction.get("source_datetime") != r["datetime"]
                        or correction.get("canonical_date") != str(f["match_date"])
                    ):
                        raise ValueError(f"Understat date contradiction: {key}")
                if (int(r["goals"]["h"]), int(r["goals"]["a"])) != (
                    f["home_goals"],
                    f["away_goals"],
                ):
                    raise ValueError(f"Understat score contradiction: {key}")
                for side, team in [("h", h), ("a", a)]:
                    xg = float(r["xG"][side])
                    if not 0 <= xg < float("inf"):
                        raise ValueError("Invalid Understat xG")
                    rows.append(
                        {
                            "match_id": key,
                            "team_id": team,
                            "competition_id": comp,
                            "season_id": season,
                            "xg": xg,
                            "source_match_id": str(r["id"]),
                        }
                    )
            return publish(root, record, {"team_process": rows})
        key = request["match_id"]
        f = fixtures[key]
        retrieved = timestamp(record["retrieved_at"])
        if context is not None:
            known = context.known_links(retrieved)
            appearances = context.match_appearances(key, retrieved)
        else:
            known = {}
            for row in data.rows(
                "SELECT DISTINCT understat_id, player_id FROM players_observations "
                "WHERE understat_id IS NOT NULL AND retrieved_at<=?",
                [record["retrieved_at"]],
            ):
                uid, player = row["understat_id"], row["player_id"]
                if uid in known and known[uid] != player:
                    raise ValueError(f"Contradictory retained player mapping: Understat {uid}")
                known[uid] = player
            appearances = data.rows(
                "SELECT DISTINCT a.team_id, a.player_id, p.name FROM appearances_observations a "
                "JOIN players_observations p USING(player_id) "
                "WHERE a.match_id=? AND p.name IS NOT NULL AND p.retrieved_at<=? "
                "AND a.retrieved_at<=?",
                [key, record["retrieved_at"], record["retrieved_at"]],
            )
        rows, identities = [], []
        for side, team in [("h", f["home_team_id"]), ("a", f["away_team_id"])]:
            for r in body["rosters"][side].values():
                uid = str(r["player_id"])
                candidates = {
                    p["player_id"]
                    for p in appearances
                    if p["team_id"] == team and name_tokens(p["name"]) == name_tokens(r["player"])
                }
                linked = known.get(uid)
                if len(candidates) == 1:
                    found = next(iter(candidates))
                    if linked and linked != found:
                        raise ValueError(f"Contradictory player mapping: Understat {uid}")
                    linked = found
                if linked:
                    identities.append(
                        {"player_id": linked, "understat_id": uid, "name": r["player"]}
                    )
                rows.append(
                    {
                        "match_id": key,
                        "team_id": team,
                        "competition_id": f["competition_id"],
                        "season_id": f["season_id"],
                        "player_id": linked,
                        "understat_id": uid,
                        "position": r["position"],
                        "minutes": int(r["time"]),
                        "xg": float(r["xG"]),
                        "xa": float(r["xA"]),
                        "shots": int(r["shots"]),
                    }
                )
        result = publish(root, record, {"player_process": rows, "players": identities})
        if context is not None:
            context.record(identities, retrieved)
        return result
    finally:
        if data is not None:
            data.close()
