"""Matchday-squad continuity: a temporary relative-strength adjustment for near fixtures.

Three concepts stay separate:

- identity: the canonical player ID of a provider record;
- membership: the club of a player at the forecast cutoff;
- fixture representation: the evidence that a player is in the target matchday squad.

The adjustment moves the log rates of one fixture. It never changes the persistent M7 state.
"""

import copy
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta

import numpy as np

from epl_forecast.live import LONDON
from epl_forecast.models.quality_tilt_scores import ScoreMixture

COMPETITIONS = ("eng-premier-league", "eng-championship")
# Fitted once on the 8,073 Premier League and Championship matches of 2017/18–2025/26 with a
# realized matchday squad for both clubs. It is not refitted on later outcomes.
KAPPA = 0.43161578781583126
# The longest checkpoint of the prospective evaluation. A later fixture gets no adjustment.
HORIZON = timedelta(days=6)
WINDOW = 8
REFERENCE_MINUTES = 90
FULL_RECENT_MINUTES = 700
STARTING_XI = 11
# The smallest bench in the 4,128 final API-Football team sheets of the Premier League and the
# Championship in 2024/25–2026/27 (most name 9). A capture with fewer substitutes does not show
# the whole matchday squad.
MIN_SUBSTITUTES = 7
# A club with more unresolved recent weight than this gets no adjustment.
MAX_UNRESOLVED = 0.25
# Before kickoff in September 2026, 25 of 87 doubtful players were in the matchday squad.
DOUBTFUL = 0.3
FPL_UNAVAILABLE = ("i", "s", "n", "u")
MEMBER = "member"
DEPARTED = "departed"
UNKNOWN = "unknown"
# The share of available club members in the next matchday squad, by the number of matchday
# squads in the previous eight club matches and inclusion in the last one. Premier League and
# Championship, 2021/22–2025/26, without players listed as injured or later shown to have left.
SQUAD_PROPENSITY = {
    (1, False): 0.29692214846107423,
    (1, True): 0.9173838209982789,
    (2, False): 0.3450737743931461,
    (2, True): 0.9107398568019093,
    (3, False): 0.39690721649484534,
    (3, True): 0.9088026855650877,
    (4, False): 0.4024691358024691,
    (4, True): 0.9071785819358635,
    (5, False): 0.4737704918032787,
    (5, True): 0.9141130772550712,
    (6, False): 0.5219683655536028,
    (6, True): 0.923648015004689,
    (7, False): 0.6280834914611005,
    (7, True): 0.9391924196983527,
    (8, True): 0.9586164696789153,
}


def first(item):
    return item[0]


def start_of_day(day):
    return datetime.combine(day, time(), tzinfo=LONDON)


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
        day = cutoff.astimezone(LONDON).date()
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
        self.fpl = {
            row["player_id"]: row
            for row in fpl_rows
            if row["retrieved_at"] == self.fpl_time and row["player_id"]
        }

    def last_for(self, player, team):
        days = [day for day, other in self.spells.get(player, ()) if other == team]
        return max(days) if days else None

    def membership(self, player, team):
        """Club membership of a player at the cutoff.

        A dated transfer or a matchday squad of another club after the last appearance for
        this club decides membership. Otherwise the latest captured squads and the FPL team
        decide when they agree. Absence from one captured squad alone is not a transfer.
        Before any squad or FPL capture exists, a player without contrary dated evidence
        stays a member.
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
        if not self.squad_times and self.fpl_time is None:
            return Membership(MEMBER, ("no squad or FPL capture at the cutoff",))
        if team in self.squads:
            return Membership(UNKNOWN, (f"absent from latest captured squad of {team}",))
        return Membership(UNKNOWN, ("no membership evidence",))

    def availability(self, player, team, match_id, competition_id):
        """Probability that a club member is available for the matchday squad of this fixture."""
        values, basis = [], []
        for row in self.injuries.get((match_id, team, player), ()):
            values.append({"unavailable": 0.0, "doubtful": DOUBTFUL}.get(row["status"]))
            basis.append(f"API-Football {row['status']}: {row['reason']}")
        fpl = self.fpl.get(player)
        if competition_id == "eng-premier-league" and fpl is not None and fpl["team_id"] == team:
            status = fpl["status"]
            if status == "a":
                values.append(1.0)
            elif status == "d":
                values.append(DOUBTFUL)
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

    def recent_weights(self, team, previous_matches):
        histories = [self.played.get((match_id, team)) for match_id in previous_matches[-WINDOW:]]
        if len(histories) < WINDOW or any(
            row is None or sum(row.values()) < FULL_RECENT_MINUTES for row in histories
        ):
            return None
        weights = defaultdict(float)
        for players in histories:
            for player, minutes in players.items():
                weights[player] += minutes
        return dict(weights)

    def team_sheet(self, match_id, team):
        """The latest official team sheet captured before kickoff with the whole matchday squad."""
        captures = self.sheets.get((match_id, team), {})
        for retrieved_at in sorted(captures, reverse=True):
            sheet = captures[retrieved_at]
            starters = sum(sheet.values())
            if starters == STARTING_XI and len(sheet) - starters >= MIN_SUBSTITUTES:
                return set(sheet), retrieved_at
        return None

    def selection(self, team, previous_matches, player):
        """Matchday squads with the player in the window, and inclusion in the last one."""
        chosen = [self.matchday.get((m, team), set()) for m in previous_matches[-WINDOW:]]
        return sum(player in row for row in chosen), bool(chosen) and player in chosen[-1]


def known_at(fixture_row):
    """When a finished club match is known: its kickoff, or the London day after its date."""
    if fixture_row["kickoff_time"] is not None:
        return fixture_row["kickoff_time"]
    return start_of_day(fixture_row["match_date"] + timedelta(days=1))


def club_histories(fixture_rows):
    histories = defaultdict(list)
    for row in fixture_rows:
        if row["stage"] == "regular" and row["status"] == "finished" and row["match_date"]:
            for team in (row["home_team_id"], row["away_team_id"]):
                histories[team].append((known_at(row), row["match_date"], row["match_id"]))
    return histories


def reference_matches(history, target_date, cutoff):
    """Club matches known at the cutoff and dated before the target, oldest first.

    `history` holds (known_at, match_date, match_id) for the finished matches of one club. A
    forecast six days before a Saturday target does not see the Wednesday match between.
    """
    return [
        match_id
        for known, day, match_id in sorted(history, key=lambda item: (item[1], item[2]))
        if day < target_date and known < cutoff
    ]


def team_continuity(evidence, team, match_id, competition_id, previous_matches):
    """Expected matchday-squad discontinuity of one club for one fixture."""
    weights = evidence.recent_weights(team, previous_matches)
    result = {
        "team_id": team,
        "reference_matches": previous_matches[-WINDOW:],
        "discontinuity": None,
        "unresolved_weight": None,
        "team_sheet_retrieved_at": None,
        "players": [],
    }
    if weights is None:
        return result
    total = sum(weights.values())
    # An official team sheet captured before the cutoff turns the expected feature into the
    # observed feature. The coefficient does not change.
    sheet = evidence.team_sheet(match_id, team)
    represented = resolved = 0.0
    for player, weight in sorted(weights.items(), key=lambda item: (-item[1], item[0])):
        membership = evidence.membership(player, team)
        selection = evidence.selection(team, previous_matches, player)
        availability, basis = None, ()
        if sheet is not None:
            probability = float(player in sheet[0])
        elif membership.state == DEPARTED:
            probability = 0.0
        elif membership.state == MEMBER:
            availability, basis = evidence.availability(player, team, match_id, competition_id)
            probability = (
                None if availability is None else availability * SQUAD_PROPENSITY[selection]
            )
        else:
            probability = None
        if probability is not None:
            represented += weight * probability
            resolved += weight
        result["players"].append(
            {
                "player_id": player,
                "recent_weight": weight / total,
                "membership": membership.state,
                "membership_basis": list(membership.basis),
                "membership_conflicts": list(membership.conflicts),
                "recent_squads": selection[0],
                "in_last_squad": selection[1],
                "availability": availability,
                "availability_basis": list(basis),
                "probability": probability,
            }
        )
    result["unresolved_weight"] = 1 - resolved / total
    result["discontinuity"] = None if not resolved else 1 - represented / resolved
    result["team_sheet_retrieved_at"] = None if sheet is None else sheet[1].isoformat()
    return result


def home_log_rate_shift(home, away):
    """κ(D_away − D_home) for the home log rate, or None when either club is not usable."""
    for team in (home, away):
        if team["discontinuity"] is None or team["unresolved_weight"] > MAX_UNRESOLVED:
            return None
    return KAPPA * (away["discontinuity"] - home["discontinuity"])


def in_horizon(fixture, kickoff, cutoff):
    return (
        fixture.competition_id in COMPETITIONS
        and kickoff is not None
        and cutoff < kickoff <= cutoff + HORIZON
    )


def fixture_adjustments(evidence, histories, fixtures, kickoffs, cutoff):
    """The personnel record of each fixture within the horizon, keyed by match ID."""
    result = {}
    for fixture in fixtures:
        if not in_horizon(fixture, kickoffs.get(fixture.match_id), cutoff):
            continue
        sides = {
            side: team_continuity(
                evidence,
                team,
                fixture.match_id,
                fixture.competition_id,
                reference_matches(histories[team], fixture.match_date, cutoff),
            )
            for side, team in (("home", fixture.home_team_id), ("away", fixture.away_team_id))
        }
        result[fixture.match_id] = {
            **sides,
            "home_log_rate_shift": home_log_rate_shift(sides["home"], sides["away"]),
        }
    return result


def shift_scores(scores, shift):
    """A copy of a score distribution with +shift on the home and −shift on the away log rate."""
    if isinstance(scores, ScoreMixture):
        return ScoreMixture([shift_scores(c, shift) for c in scores.components], scores.weights)
    shifted = copy.copy(scores)
    shifted.log_mean = scores.log_mean + np.array([shift, -shift])
    shifted.home_rates = scores.home_rates * np.exp(shift)
    shifted.away_rates = scores.away_rates * np.exp(-shift)
    shifted.home_rate = float(shifted.weights @ shifted.home_rates)
    shifted.away_rate = float(shifted.weights @ shifted.away_rates)
    return shifted


def season_ids(cutoff):
    year = cutoff.year - (cutoff.month < 7)
    return f"{year - 1}-{year}", f"{year}-{year + 1}"


def load_evidence(data, seasons):
    """Personnel rows from a cutoff-filtered `Dataset`; no odds and no model inputs."""
    placeholders = ", ".join("?" for _ in seasons)
    days = {row["match_id"]: row["match_date"] for row in data.fixtures()}
    appearances = data.rows(
        "SELECT match_id, team_id, player_id, starts, minutes, kickoff_time, retrieved_at "
        f"FROM appearances_observations WHERE season_id IN ({placeholders}) "
        "AND player_id IS NOT NULL",
        list(seasons),
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
            list(seasons),
        ),
        "transfers": data.rows(
            "SELECT player_id, transfer_date, from_team_id, to_team_id, retrieved_at "
            "FROM transfers_observations WHERE player_id IS NOT NULL"
        ),
        "injuries": data.rows(
            "SELECT match_id, team_id, player_id, competition_id, status, reason, retrieved_at "
            "FROM availability_observations WHERE provider='api_football' "
            f"AND scope LIKE 'fixture:%' AND season_id IN ({placeholders})",
            list(seasons),
        ),
        "fpl": data.rows(
            "SELECT player_id, team_id, status, reason, retrieved_at FROM availability_observations "
            f"WHERE provider='fpl' AND season_id IN ({placeholders})",
            list(seasons),
        ),
    }


def current_adjustments(data, fixtures, kickoffs, cutoff):
    """Adjustments at a cutoff from a `Dataset` filtered to that cutoff."""
    if not any(in_horizon(f, kickoffs.get(f.match_id), cutoff) for f in fixtures):
        return {}
    evidence = Evidence(cutoff, **load_evidence(data, season_ids(cutoff)))
    return fixture_adjustments(
        evidence, club_histories(data.fixtures()), fixtures, kickoffs, cutoff
    )


def dated_history(appearances, transfers):
    """Evidence rows for a retrospective origin, dated by the events that history records.

    A matchday squad is known from the London day after its match, and a transfer from the start
    of its London day. History has no squad captures, injury lists or FPL snapshots.
    """
    return {
        "appearances": [
            {
                **row,
                "kickoff_time": row["kickoff_time"] or start_of_day(row["match_date"]),
                "retrieved_at": start_of_day(row["match_date"] + timedelta(days=1)),
            }
            for row in appearances
            if row["match_date"] is not None
        ],
        "transfers": [
            {**row, "retrieved_at": start_of_day(row["transfer_date"])}
            for row in transfers
            if row["transfer_date"] is not None
        ],
    }
