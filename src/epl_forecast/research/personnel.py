"""Cutoff-safe expected personnel continuity for one structural forecast.

Three concepts stay separate:

- identity: the canonical player ID of a provider record;
- membership: the club of a player at the forecast cutoff;
- fixture representation: the evidence that a player is in the target matchday team.

The same estimator runs at any cutoff. It gives two representations of the recent personnel
that the target fixture keeps: the starting XI and the matchday squad.
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

STARTING_XI = 11
# The smallest bench in the 4,128 final API-Football team sheets of the Premier League and the
# Championship in 2024/25–2026/27 (most name 9). A capture with fewer substitutes does not show
# the whole matchday squad.
MIN_SUBSTITUTES = 7
MEMBER = "member"
DEPARTED = "departed"
UNKNOWN = "unknown"
REPRESENTATIONS = ("xi", "squad")
# Before kickoff in September 2026, doubtful players started 8 of 87 times and were in the
# matchday squad 25 of 87 times (API-Football and FPL together).
DOUBTFUL = {"xi": 0.1, "squad": 0.3}
FPL_UNAVAILABLE = ("i", "s", "n", "u")
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
        self.played = defaultdict(dict)
        self.started = defaultdict(set)
        self.matchday = defaultdict(set)
        spells = defaultdict(set)
        self.sheets = defaultdict(lambda: defaultdict(dict))
        for row in appearances:
            kickoff = row["kickoff_time"]
            if row["retrieved_at"] > cutoff or kickoff is None:
                continue
            key = row["match_id"], row["team_id"]
            if row["retrieved_at"] < kickoff:
                self.sheets[key][row["retrieved_at"]][row["player_id"]] = bool(row["starts"])
            if kickoff >= cutoff:
                continue
            spells[row["player_id"]].add((row["match_date"], row["team_id"]))
            self.matchday[key].add(row["player_id"])
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

    def availability(self, player, team, match_id, competition_id, representation):
        """Probability that a club member is available for this club, fixture and representation."""
        values, basis = [], []
        for row in self.injuries.get((match_id, team, player), ()):
            values.append(
                {"unavailable": 0.0, "doubtful": DOUBTFUL[representation]}.get(row["status"])
            )
            basis.append(f"API-Football {row['status']}: {row['reason']}")
        fpl = self.fpl.get(player)
        if competition_id == "eng-premier-league" and fpl is not None and fpl["team_id"] == team:
            status = fpl["status"]
            if status == "a":
                values.append(1.0)
            elif status == "d":
                values.append(DOUBTFUL[representation])
            elif status in FPL_UNAVAILABLE:
                values.append(0.0)
            else:
                values.append(None)
            basis.append(f"FPL {status}: {fpl['reason']}")
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

    def team_sheet(self, match_id, team):
        """The latest official team sheet captured before kickoff with the whole matchday squad.

        A capture shows the whole matchday squad when it has 11 starters and at least
        `MIN_SUBSTITUTES` substitutes. Otherwise the feature stays expected.
        """
        captures = self.sheets.get((match_id, team), {})
        for retrieved_at in sorted(captures, reverse=True):
            sheet = captures[retrieved_at]
            starters = {player for player, starts in sheet.items() if starts}
            if len(starters) == STARTING_XI and len(sheet) - len(starters) >= MIN_SUBSTITUTES:
                return {"xi": starters, "squad": set(sheet)}, retrieved_at
        return None

    def selection(self, team, previous_matches, player, window=WINDOW):
        """Recent starts and matchday squads, each with inclusion in the last window match."""
        previous = previous_matches[-window:]
        result = {}
        for representation, source in (("xi", self.started), ("squad", self.matchday)):
            chosen = [source.get((match_id, team), set()) for match_id in previous]
            result[representation] = (
                sum(player in row for row in chosen),
                bool(chosen) and player in chosen[-1],
            )
        return result


def reference_matches(history, target_date, cutoff):
    """Club matches known at the cutoff: kickoff before the cutoff and date before the target.

    `history` holds (kickoff_time, match_date, match_id) for the finished matches of one club.
    A forecast six days before a Saturday target does not see the Wednesday match between.
    """
    ordered = sorted(history, key=lambda item: (item[1], item[2]))
    return [
        match_id
        for kickoff, day, match_id in ordered
        if day < target_date and kickoff is not None and kickoff < cutoff
    ]


def load_propensity(path=PROPENSITY_FILE):
    data = json.loads(Path(path).read_text())
    return {
        "xi": {(row["starts"], row["started_last"]): row["rate"] for row in data["table"]},
        "squad": {
            (row["squads"], row["in_last_squad"]): row["rate"] for row in data["squad_table"]
        },
    }


def realized_discontinuity(weights, represented):
    """Discontinuity for a realized set: the starting XI, or the whole matchday squad."""
    total = sum(weights.values())
    return 1 - sum(weight for player, weight in weights.items() if player in represented) / total


def expected_discontinuity(weights, probabilities):
    """Expected discontinuity over resolved players, and the unresolved weight share."""
    total = sum(weights.values())
    resolved = {p: w for p, w in weights.items() if probabilities.get(p) is not None}
    unresolved = 1 - sum(resolved.values()) / total
    if not resolved:
        return None, unresolved
    represented = sum(weight * probabilities[player] for player, weight in resolved.items())
    return 1 - represented / sum(resolved.values()), unresolved


def team_expected(evidence, team, match_id, competition_id, previous_matches, propensity):
    weights = evidence.recent_weights(team, previous_matches)
    if weights is None:
        return None
    total = sum(weights.values())
    probabilities = {representation: {} for representation in REPRESENTATIONS}
    players = []
    # An official team sheet captured before the cutoff turns the expected feature into the
    # observed feature. The estimator and its coefficients do not change.
    sheet = evidence.team_sheet(match_id, team)
    for player, weight in sorted(weights.items(), key=lambda item: (-item[1], item[0])):
        membership = evidence.membership(player, team)
        selection = evidence.selection(team, previous_matches, player)
        row = {
            "player_id": player,
            "recent_minutes": weight,
            "recent_weight": weight / total,
            "membership": membership.state,
            "membership_basis": list(membership.basis),
            "membership_conflicts": list(membership.conflicts),
            "selection": {r: list(value) for r, value in selection.items()},
            "availability": {},
            "availability_basis": [],
            "probability": {},
        }
        for representation in REPRESENTATIONS:
            probability = None
            if sheet is not None:
                probability = float(player in sheet[0][representation])
            elif membership.state == DEPARTED:
                probability = 0.0
            elif membership.state == MEMBER:
                availability, basis = evidence.availability(
                    player, team, match_id, competition_id, representation
                )
                row["availability"][representation] = availability
                row["availability_basis"] = list(basis)
                if availability is not None:
                    rate = propensity[representation][selection[representation]]
                    probability = availability * rate
            probabilities[representation][player] = probability
            row["probability"][representation] = probability
        players.append(row)
    result = {
        "players": players,
        "team_sheet_retrieved_at": None if sheet is None else sheet[1].isoformat(),
    }
    for representation in REPRESENTATIONS:
        d, unresolved = expected_discontinuity(weights, probabilities[representation])
        result[representation] = {"d": d, "unresolved_weight": unresolved}
    return result


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
