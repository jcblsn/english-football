"""Calibrate recent starter propensity for available club members."""

import argparse
from collections import defaultdict
from pathlib import Path

from epl_forecast.artifacts import execution_provenance, new_run_directory
from epl_forecast.datasets import Dataset
from epl_forecast.live import LONDON
from epl_forecast.research.personnel_mean import FULL_RECENT_MINUTES, WINDOW, lineup_minutes
from epl_forecast.research.roster import RosterEvidence
from epl_forecast.storage import load_environment, write_json

COMPETITIONS = ("eng-premier-league", "eng-championship")
SEASONS = ("2021-2022", "2022-2023", "2023-2024", "2024-2025", "2025-2026")


def main():
    load_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    new_run_directory(args.output)
    data = Dataset(args.data)
    try:
        matches = data.matches()
        played = data.player_history()
        squads = data.rows(
            "SELECT match_id, team_id, player_id, season_id, kickoff_time, starts "
            "FROM appearances WHERE player_id IS NOT NULL"
        )
        transfers = data.rows(
            "SELECT player_id, transfer_date, from_team_id, to_team_id FROM transfers"
        )
        injuries = data.rows(
            "SELECT DISTINCT match_id, team_id, player_id FROM availability "
            "WHERE provider='api_football' AND scope LIKE 'fixture:%' AND player_id IS NOT NULL"
        )
    finally:
        data.close()
    days = {match.fixture.match_id: match.fixture.match_date for match in matches}
    dated = []
    for row in squads:
        day = days.get(row["match_id"])
        if day is None and row["kickoff_time"] is not None:
            day = row["kickoff_time"].astimezone(LONDON).date()
        if day is not None:
            dated.append({**row, "match_date": day})
    evidence = RosterEvidence(dated, transfers)
    listed = {(row["match_id"], row["team_id"], row["player_id"]) for row in injuries}
    minutes = lineup_minutes(played)
    starters = lineup_minutes(played, starters=True)
    by_team = defaultdict(list)
    for match in sorted(matches, key=lambda item: (item.fixture.match_date, item.fixture.match_id)):
        for team in (match.fixture.home_team_id, match.fixture.away_team_id):
            by_team[team].append(match)
    cells = defaultdict(lambda: [0, 0])
    excluded = defaultdict(int)
    for team, games in by_team.items():
        for index, match in enumerate(games):
            fixture = match.fixture
            if fixture.competition_id not in COMPETITIONS or fixture.season_id not in SEASONS:
                continue
            previous = [g for g in games[:index] if g.fixture.match_date < fixture.match_date]
            previous = previous[-WINDOW:]
            histories = [minutes.get((g.fixture.match_id, team)) for g in previous]
            target = starters.get((fixture.match_id, team))
            if (
                target is None
                or len(target) != 11
                or len(histories) < WINDOW
                or any(row is None or sum(row.values()) < FULL_RECENT_MINUTES for row in histories)
            ):
                continue
            started = [set(starters.get((g.fixture.match_id, team), {})) for g in previous]
            for player in {player for row in histories for player in row}:
                if (fixture.match_id, team, player) in listed:
                    excluded["listed injured or doubtful"] += 1
                    continue
                if evidence.departed(player, team, fixture.match_date):
                    excluded["departed"] += 1
                    continue
                cell = cells[sum(player in row for row in started), player in started[-1]]
                cell[0] += 1
                cell[1] += player in target
    table = [
        {
            "starts": starts,
            "started_last": last,
            "players": count,
            "started": hits,
            "rate": hits / count,
        }
        for (starts, last), (count, hits) in sorted(cells.items())
    ]
    result = {
        "execution": execution_provenance(),
        "competitions": COMPETITIONS,
        "seasons": SEASONS,
        "window": WINDOW,
        "population": "players with minutes in the previous eight matches, excluding players "
        "listed by API-Football for the target fixture and players with later evidence that "
        "they left the club",
        "excluded": dict(excluded),
        "table": table,
    }
    write_json(args.output / "start_propensity.json", result)
    for row in table:
        print(row)
    print(dict(excluded))


if __name__ == "__main__":
    main()
