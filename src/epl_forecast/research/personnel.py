"""Cutoff-safe personnel evidence for the starting-XI continuity experiment.

Three concepts stay separate:

- identity: the canonical player ID of a provider record;
- membership: the club of a player at the forecast cutoff;
- fixture representation: the evidence that a player starts the target fixture.
"""

import copy
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from epl_forecast.live import LONDON
from epl_forecast.research.personnel_mean import (
    FULL_RECENT_MINUTES,
    REFERENCE_MINUTES,
    WINDOW,
    quality_shift,
)

MEMBER = "member"
DEPARTED = "departed"
UNKNOWN = "unknown"
STARTING_XI = 11
# Before kickoff in September 2026, 7 of 74 API-Football doubtful players and 1 of 15 FPL
# doubtful players started. A doubtful listing is therefore weak evidence of a start.
DOUBTFUL = 0.1
FPL_STATUS = {"a": 1.0, "d": DOUBTFUL, "i": 0.0, "s": 0.0, "n": 0.0, "u": 0.0}
API_STATUS = {"unavailable": 0.0, "doubtful": DOUBTFUL}
# An estimate with more unresolved recent weight than this is not used for a candidate.
MAX_UNRESOLVED = 0.25
PROPENSITY_FILE = Path(__file__).with_name("start_propensity.json")


def first(item):
    return item[0]


def cutoff_day(cutoff):
    return cutoff.astimezone(LONDON).date()


@dataclass(frozen=True)
class Membership:
    state: str
    basis: tuple = ()
    conflicts: tuple = ()


class Evidence:
    """Personnel observations that a forecast at `cutoff` can use.

    Each row carries `retrieved_at`. Rows retrieved after the cutoff are ignored, so a later
    observation cannot change a result. Appearance rows also need `match_date`.
    """

    def __init__(self, cutoff, *, appearances=(), squads=(), transfers=(), injuries=(), fpl=()):
        self.cutoff = cutoff
        visible = [row for row in appearances if row["retrieved_at"] <= cutoff]
        self.played = defaultdict(dict)
        self.started = defaultdict(set)
        spells = defaultdict(set)
        self.lineups = defaultdict(lambda: defaultdict(dict))
        for row in visible:
            kickoff = row["kickoff_time"]
            if kickoff is None:
                continue
            key = row["match_id"], row["team_id"]
            if row["retrieved_at"] < kickoff:
                self.lineups[key][row["retrieved_at"]][row["player_id"]] = bool(row["starts"])
            if kickoff >= cutoff:
                continue
            spells[row["player_id"]].add((row["match_date"], row["team_id"]))
            if row["starts"]:
                self.started[key].add(row["player_id"])
            if row["minutes"] is not None:
                self.played[key][row["player_id"]] = min(int(row["minutes"]), REFERENCE_MINUTES)
        self.spells = {player: sorted(rows, key=first) for player, rows in spells.items()}
        self.squad_times = {}
        for row in squads:
            if row["retrieved_at"] <= cutoff:
                team = row["team_id"]
                self.squad_times[team] = max(
                    self.squad_times.get(team, row["retrieved_at"]), row["retrieved_at"]
                )
        self.squads = defaultdict(set)
        self.squad_teams = defaultdict(set)
        for row in squads:
            if row["retrieved_at"] == self.squad_times.get(row["team_id"]):
                self.squads[row["team_id"]].add(row["player_id"])
                self.squad_teams[row["player_id"]].add(row["team_id"])
        day = cutoff_day(cutoff)
        self.transfers = defaultdict(list)
        for row in transfers:
            if (
                row["retrieved_at"] <= cutoff
                and row["transfer_date"] is not None
                and row["transfer_date"] <= day
            ):
                self.transfers[row["player_id"]].append(
                    (row["transfer_date"], row["from_team_id"], row["to_team_id"])
                )
        latest = {}
        for row in injuries:
            if row["retrieved_at"] <= cutoff:
                key = row["competition_id"]
                latest[key] = max(latest.get(key, row["retrieved_at"]), row["retrieved_at"])
        self.injury_times = latest
        self.injuries = defaultdict(list)
        for row in injuries:
            if row["player_id"] and row["retrieved_at"] == latest.get(row["competition_id"]):
                self.injuries[row["match_id"], row["team_id"], row["player_id"]].append(row)
        fpl_rows = [row for row in fpl if row["retrieved_at"] <= cutoff]
        self.fpl_time = max((row["retrieved_at"] for row in fpl_rows), default=None)
        current = [row for row in fpl_rows if row["retrieved_at"] == self.fpl_time]
        self.fpl = {row["player_id"]: row for row in current if row["player_id"]}
        self.fpl_unresolved = [row for row in current if not row["player_id"]]

    def last_for(self, player, team):
        days = [day for day, other in self.spells.get(player, ()) if other == team]
        return max(days) if days else None

    def membership(self, player, team):
        """Club membership of a player at the cutoff.

        A dated transfer or a matchday squad of another club after the last appearance for
        this club decides membership. Otherwise the latest captured squads and the FPL team
        decide when they agree. Absence from one captured squad alone is not a transfer.
        """
        since = self.last_for(player, team)
        strong = []
        for day, source, destination in self.transfers.get(player, ()):
            if since is not None and day <= since:
                continue
            if source == team and destination != team:
                strong.append((day, DEPARTED, f"transfer from {team} to {destination} on {day}"))
            elif destination == team and source != team:
                strong.append((day, MEMBER, f"transfer from {source} to {team} on {day}"))
        for day, other in self.spells.get(player, ()):
            if other != team and (since is None or day > since):
                strong.append((day, DEPARTED, f"matchday squad of {other} on {day}"))
        weak = []
        if team in self.squad_teams.get(player, ()):
            weak.append((MEMBER, f"latest captured squad of {team}"))
        for other in sorted(self.squad_teams.get(player, set()) - {team}):
            weak.append((DEPARTED, f"latest captured squad of {other}"))
        fpl = self.fpl.get(player)
        if fpl is not None:
            weak.append(
                (MEMBER if fpl["team_id"] == team else DEPARTED, f"FPL team {fpl['team_id']}")
            )
        if strong:
            strong.sort(key=first)
            state = strong[-1][1]
            conflicts = tuple(basis for other, basis in weak if other != state)
            return Membership(state, tuple(item[2] for item in strong), conflicts)
        states = {state for state, _ in weak}
        if len(states) == 1:
            return Membership(states.pop(), tuple(basis for _, basis in weak))
        if states:
            return Membership(UNKNOWN, (), tuple(basis for _, basis in weak))
        if team in self.squads:
            return Membership(UNKNOWN, (f"absent from latest captured squad of {team}",))
        return Membership(UNKNOWN, ("no membership evidence",))

    def availability(self, player, team, match_id, competition_id):
        """Probability that a club member is available to start this fixture for this club."""
        values, basis = [], []
        for row in self.injuries.get((match_id, team, player), ()):
            values.append(API_STATUS.get(row["status"]))
            basis.append(f"API-Football {row['status']}: {row['reason']}")
        fpl = self.fpl.get(player)
        if competition_id == "eng-premier-league" and fpl is not None and fpl["team_id"] == team:
            values.append(FPL_STATUS.get(fpl["status"]))
            basis.append(f"FPL {fpl['status']}: {fpl['reason']}")
        if any(value is None for value in values):
            return None, (*basis, "unknown provider status")
        if not values:
            return 1.0, ("no contrary availability evidence",)
        if min(values) == 0.0 and max(values) == 1.0:
            return None, (*basis, "providers conflict")
        return min(values), tuple(basis)

    def recent_weights(self, team, previous_matches, window=WINDOW):
        histories = [self.played.get((match_id, team)) for match_id in previous_matches[-window:]]
        if len(histories) < window or any(
            row is None or sum(row.values()) < FULL_RECENT_MINUTES for row in histories
        ):
            return None
        weights = defaultdict(float)
        for players in histories:
            for player, minutes in players.items():
                weights[player] += minutes
        return dict(weights)

    def starts(self, team, previous_matches, player, window=WINDOW):
        """Recent starts of a player for this club, and whether the player started the last match."""
        started = [
            self.started.get((match_id, team), set()) for match_id in previous_matches[-window:]
        ]
        return sum(player in row for row in started), bool(started) and player in started[-1]

    def confirmed_starters(self, match_id, team):
        """The starting XI of the latest capture before kickoff, or None."""
        captures = self.lineups.get((match_id, team), {})
        for retrieved_at in sorted(captures, reverse=True):
            starters = {player for player, starts in captures[retrieved_at].items() if starts}
            if len(starters) == STARTING_XI:
                return starters, retrieved_at
        return None


def load_propensity(path=PROPENSITY_FILE):
    table = json.loads(Path(path).read_text())["table"]
    return {(row["starts"], row["started_last"]): row["rate"] for row in table}


def confirmed_discontinuity(weights, starters):
    """Starting-XI discontinuity. Substitutes and unused players are not represented."""
    total = sum(weights.values())
    return 1 - sum(weight for player, weight in weights.items() if player in starters) / total


def expected_discontinuity(weights, probabilities):
    """Expected discontinuity over resolved players, and the unresolved weight share."""
    total = sum(weights.values())
    resolved = {p: w for p, w in weights.items() if probabilities.get(p) is not None}
    unresolved = 1 - sum(resolved.values()) / total
    if not resolved:
        return None, unresolved
    represented = sum(weight * probabilities[player] for player, weight in resolved.items())
    return 1 - represented / sum(resolved.values()), unresolved


def team_confirmed(evidence, team, match_id, previous_matches):
    weights = evidence.recent_weights(team, previous_matches)
    lineup = evidence.confirmed_starters(match_id, team)
    if weights is None or lineup is None:
        return None
    starters, retrieved_at = lineup
    return {
        "d": confirmed_discontinuity(weights, starters),
        "lineup_retrieved_at": retrieved_at,
        "starters": sorted(starters),
    }


def team_expected(evidence, team, match_id, competition_id, previous_matches, propensity):
    weights = evidence.recent_weights(team, previous_matches)
    if weights is None:
        return None
    total = sum(weights.values())
    probabilities, players = {}, []
    for player, weight in sorted(weights.items(), key=lambda item: (-item[1], item[0])):
        membership = evidence.membership(player, team)
        starts, last = evidence.starts(team, previous_matches, player)
        availability, availability_basis, probability = None, (), None
        if membership.state == DEPARTED:
            probability = 0.0
        elif membership.state == MEMBER:
            availability, availability_basis = evidence.availability(
                player, team, match_id, competition_id
            )
            if availability is not None:
                probability = availability * propensity[starts, last]
        probabilities[player] = probability
        players.append(
            {
                "player_id": player,
                "recent_minutes": weight,
                "recent_weight": weight / total,
                "recent_starts": starts,
                "started_last": last,
                "membership": membership.state,
                "membership_basis": list(membership.basis),
                "membership_conflicts": list(membership.conflicts),
                "availability": availability,
                "availability_basis": list(availability_basis),
                "start_probability": probability,
            }
        )
    d, unresolved = expected_discontinuity(weights, probabilities)
    return {"d": d, "unresolved_weight": unresolved, "players": players}


def candidate_shift(home, away, kappa):
    """The temporary log-rate shift, or None when either team estimate is not usable."""
    for team in (home, away):
        if team is None or team["d"] is None or team.get("unresolved_weight", 0.0) > MAX_UNRESOLVED:
            return None
    return quality_shift(home["d"], away["d"], kappa)


def structural_spec(competition_id, data_root, cutoff):
    """The product M7 structural match model; no market pool enters this forecast."""
    from epl_forecast.cli import load_config

    config = load_config(Path("configs/product.toml"))
    config["competition_id"] = competition_id
    spec = copy.deepcopy(next(item for item in config["models"] if item["id"] == "M7-xg-v1"))
    spec["parameters"].update(
        competition_id=competition_id, data_root=str(data_root), data_cutoff=cutoff.isoformat()
    )
    config["models"] = [spec]
    return config, spec


def load_evidence(data, season_ids):
    """Personnel rows from a cutoff-filtered `Dataset`; no odds and no model inputs."""
    placeholders = ", ".join("?" for _ in season_ids)
    days = {row["match_id"]: row["match_date"] for row in data.fixtures()}
    appearances = data.rows(
        "SELECT match_id, team_id, player_id, starts, minutes, kickoff_time, retrieved_at "
        f"FROM appearances_observations WHERE season_id IN ({placeholders}) "
        "AND player_id IS NOT NULL",
        list(season_ids),
    )
    for row in appearances:
        row["match_date"] = days.get(row["match_id"])
        if row["match_date"] is None and row["kickoff_time"] is not None:
            row["match_date"] = row["kickoff_time"].astimezone(LONDON).date()
    return {
        "appearances": appearances,
        "squads": data.rows(
            "SELECT player_id, team_id, retrieved_at FROM memberships_observations "
            f"WHERE basis='captured_squad' AND season_id IN ({placeholders})",
            list(season_ids),
        ),
        "transfers": data.rows(
            "SELECT player_id, transfer_date, from_team_id, to_team_id, retrieved_at "
            "FROM transfers_observations WHERE player_id IS NOT NULL"
        ),
        "injuries": data.rows(
            "SELECT match_id, team_id, player_id, competition_id, status, reason, retrieved_at "
            "FROM availability_observations WHERE provider='api_football' "
            f"AND scope LIKE 'fixture:%' AND season_id IN ({placeholders})",
            list(season_ids),
        ),
        "fpl": data.rows(
            "SELECT player_id, fpl_code, team_id, status, reason, chance_this_round, "
            "chance_next_round, retrieved_at FROM availability_observations "
            f"WHERE provider='fpl' AND season_id IN ({placeholders})",
            list(season_ids),
        ),
    }
