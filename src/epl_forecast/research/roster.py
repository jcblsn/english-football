"""Split realized starting-XI discontinuity by club membership at the target date."""

from bisect import bisect_left, bisect_right
from collections import defaultdict

from epl_forecast.research.personnel_mean import (
    FULL_RECENT_MINUTES,
    FULL_STARTING_MINUTES,
    WINDOW,
    lineup_minutes,
)

DEPARTED = "departed"
BENCHED = "benched"
RETAINED = "retained"
UNRESOLVED = "unresolved"
CLASSES = (DEPARTED, BENCHED, RETAINED, UNRESOLVED)


def first(item):
    return item[0]


class RosterEvidence:
    """Dated matchday-squad appearances and provider transfers for each player."""

    def __init__(self, squad_rows, transfer_rows):
        spells = defaultdict(list)
        for row in squad_rows:
            spells[row["player_id"]].append((row["match_date"], row["team_id"], row["season_id"]))
        self.spells = {player: sorted(rows, key=first) for player, rows in spells.items()}
        self.spell_days = {player: [row[0] for row in rows] for player, rows in self.spells.items()}
        transfers = defaultdict(list)
        for row in transfer_rows:
            if row["transfer_date"] is not None:
                transfers[row["player_id"]].append(
                    (row["transfer_date"], row["from_team_id"], row["to_team_id"])
                )
        self.transfers = {player: sorted(rows, key=first) for player, rows in transfers.items()}

    def _spells_between(self, player, start, end):
        days = self.spell_days.get(player, [])
        return self.spells.get(player, [])[bisect_right(days, start) : bisect_left(days, end)]

    def last_for(self, player, team, target):
        days = self.spell_days.get(player, [])
        for day, other, _ in reversed(self.spells.get(player, [])[: bisect_left(days, target)]):
            if other == team:
                return day
        return None

    def departed(self, player, team, target):
        """True when dated evidence after the last team appearance shows the player left."""
        since = self.last_for(player, team, target)
        if since is None:
            return False
        events = [
            (day, source == team, destination == team)
            for day, source, destination in self.transfers.get(player, ())
            if since < day <= target and team in (source, destination)
        ]
        events.extend(
            (day, True, False)
            for day, other, _ in self._spells_between(player, since, target)
            if other != team
        )
        left = False
        for _, out, back in sorted(events, key=first):
            left = (left or out) and not back
        return left

    def plays_later(self, player, team, target, season):
        days = self.spell_days.get(player, [])
        return any(
            other == team and other_season == season
            for _, other, other_season in self.spells.get(player, [])[bisect_right(days, target) :]
        )

    def classify(self, player, team, target, season, matchday_squad):
        if player in matchday_squad:
            return BENCHED
        if self.departed(player, team, target):
            return DEPARTED
        if self.plays_later(player, team, target, season):
            return RETAINED
        return UNRESOLVED


def continuity_components(matches, appearance_rows, squad_rows, transfer_rows, window=WINDOW):
    """Starting-XI discontinuity and its membership components for each team-match.

    `appearance_rows` are the rows with recorded minutes, as in `realized_continuity`.
    `squad_rows` hold every matchday-squad row, with a London `match_date`.
    """
    evidence = RosterEvidence(squad_rows, transfer_rows)
    squads = defaultdict(set)
    for row in squad_rows:
        squads[row["match_id"], row["team_id"]].add(row["player_id"])
    recent = lineup_minutes(appearance_rows)
    target = lineup_minutes(appearance_rows, starters=True)
    by_team = defaultdict(list)
    for match in sorted(matches, key=lambda item: (item.fixture.match_date, item.fixture.match_id)):
        for team in (match.fixture.home_team_id, match.fixture.away_team_id):
            by_team[team].append(match)
    result = {}
    for team, games in by_team.items():
        for index, match in enumerate(games):
            fixture = match.fixture
            previous = [
                game for game in games[:index] if game.fixture.match_date < fixture.match_date
            ]
            previous = previous[-window:]
            histories = [recent.get((game.fixture.match_id, team)) for game in previous]
            starters = target.get((fixture.match_id, team))
            if (
                starters is None
                or sum(starters.values()) < FULL_STARTING_MINUTES
                or len(histories) < window
                or any(row is None or sum(row.values()) < FULL_RECENT_MINUTES for row in histories)
            ):
                result[fixture.match_id, team] = None
                continue
            weights = defaultdict(float)
            for players in histories:
                for player, minutes in players.items():
                    weights[player] += minutes
            total = sum(weights.values())
            components = dict.fromkeys(CLASSES, 0.0)
            for player, weight in weights.items():
                if player in starters:
                    continue
                label = evidence.classify(
                    player,
                    team,
                    fixture.match_date,
                    fixture.season_id,
                    squads.get((fixture.match_id, team), set()),
                )
                components[label] += weight / total
            represented = sum(weight for player, weight in weights.items() if player in starters)
            result[fixture.match_id, team] = {"d": 1 - represented / total, **components}
    return result
