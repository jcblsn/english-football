"""FPL's narrow prospective availability signal; never historical squads or statistics."""

import json

from epl_forecast.data.api_football import team_registry
from epl_forecast.data.understat_ingest import name_tokens
from epl_forecast.datasets import Dataset, publish, timestamp
from epl_forecast.snapshots import (
    FPL_AVAILABILITY,
    SQUAD,
    SnapshotIndex,
    capture_of,
    snapshot,
    snapshot_rows,
)

URL = "https://fantasy.premierleague.com/api/bootstrap-static/"


def ingest(root, record, payload):
    b = json.loads(payload)
    aliases = team_registry()
    aliases.update(
        {
            "Spurs": "tottenham-hotspur",
            "Man Utd": "manchester-united",
            "Man City": "manchester-city",
            "Nott'm Forest": "nottingham-forest",
        }
    )
    teams = {t["id"]: aliases[t["name"]] for t in b["teams"]}
    current = next((e["id"] for e in b["events"] if e["is_current"]), None)
    upcoming = next((e["id"] for e in b["events"] if e["is_next"]), None)
    data = Dataset(root)
    try:
        players = data.rows("SELECT * FROM players_observations")
        known = {}
        for player in players:
            code = player["fpl_code"]
            if code:
                if code in known and known[code] != player["player_id"]:
                    raise ValueError(f"Conflicting canonical FPL mapping: {code}")
                known[code] = player["player_id"]
        identities, names = {}, {}
        for player in players:
            if player["name"]:
                names.setdefault(player["player_id"], set()).add(name_tokens(player["name"]))
            if player["name"] and player["birth_date"]:
                key = name_tokens(player["name"]), str(player["birth_date"])
                identities.setdefault(key, set()).add(player["player_id"])
        team_birthdays = {}
        births = {p["player_id"]: str(p["birth_date"]) for p in players if p["birth_date"]}
        # One definition of "the latest captured squad" for the whole product. A manifest
        # scan cannot serve as that definition, because compaction collapses the request
        # contexts it reads.
        index = SnapshotIndex(snapshot_rows(data), timestamp(record["retrieved_at"]))
        by_team = {}
        for member in data.rows(
            "SELECT player_id, team_id, retrieved_at, source_sha256 "
            "FROM memberships_observations WHERE basis='captured_squad' AND season_id=?",
            [record["context"]["season_id"]],
        ):
            by_team.setdefault(member["team_id"], []).append(member)
        for team in index.keys(SQUAD):
            identity = index.identity(SQUAD, team)
            for member in by_team.get(team, ()):
                if capture_of(member) != identity or member["player_id"] not in births:
                    continue
                key = team, births[member["player_id"]]
                team_birthdays.setdefault(key, set()).add(member["player_id"])
        rows, mappings = [], []
        for p in b["elements"]:
            if p["element_type"] not in (1, 2, 3, 4):
                continue
            code = str(p["code"])
            pid = known.get(code)
            full = name_tokens(p["first_name"] + " " + p["second_name"])
            candidates = identities.get((full, p.get("birth_date")), set())
            if not candidates:
                candidates = team_birthdays.get((teams[p["team"]], p.get("birth_date")), set())
                tokens = full.split()
                candidates = {
                    candidate
                    for candidate in candidates
                    if any(
                        tokens
                        and alias.split()
                        and (
                            tokens[0].startswith(alias.split()[0])
                            or alias.split()[0].startswith(tokens[0])
                        )
                        and set(tokens[1:]) & set(alias.split()[1:])
                        for alias in names.get(candidate, set())
                    )
                }
            if len(candidates) == 1:
                candidate = next(iter(candidates))
                if pid and candidate != pid:
                    raise ValueError(f"Conflicting FPL code mapping: {code}")
                pid = candidate
            if pid:
                mappings.append({"player_id": pid, "fpl_code": code})
            rows.append(
                {
                    "player_id": pid,
                    "fpl_code": code,
                    "team_id": teams[p["team"]],
                    "competition_id": "eng-premier-league",
                    "season_id": record["context"]["season_id"],
                    "scope": "fpl_round",
                    "status": p["status"],
                    "reason": p["news"],
                    "chance_this_round": p.get("chance_of_playing_this_round"),
                    "chance_next_round": p.get("chance_of_playing_next_round"),
                    "current_round": current,
                    "next_round": upcoming,
                    "news_added": p.get("news_added"),
                }
            )
        season = record["context"]["season_id"]
        return publish(
            root,
            record,
            {
                "availability": rows,
                "players": mappings,
                "source_snapshots": [
                    snapshot(
                        FPL_AVAILABILITY,
                        season,
                        endpoint="bootstrap-static",
                        row_count=len(rows),
                        competition_id="eng-premier-league",
                        season_id=season,
                    )
                ],
            },
        )
    finally:
        data.close()
