"""Sanctioned league tables derived from retained provider standings.

Archived results give the points a team earned on the pitch. They do not record
disciplinary or financial sanctions, so a table computed from results alone is not
the table the competition actually finished on. The retained API-Football standings
are the provider's own table, sanctions included; the difference between a team's
standings points and the points its archived results imply is that team's net
adjustment.

A difference is only evidence of a sanction when the two tables describe the same
matches, so every team is checked against the prefix of its own fixtures that the
provider says it had played, and the provider's goal difference must agree with the
archive over that prefix. Teams that fail the check are reported as unknown rather
than silently credited with an adjustment; a season whose snapshot is a partial
mid-season table fails for nearly every team and yields no sanctioned table at all.

Two views come out of the same derivation. ``final_adjustments`` is truth: what the
completed table says, used to score a finished season. ``known_adjustments`` is what
a forecaster could have applied at a cutoff, which needs a date the sanction was
knowable. Reviewed registries carry real announcement dates; a derived adjustment
carries only the date its standings snapshot was retrieved, so a sanction seen for
the first time in a retrospective capture is knowable to no in-season forecast.
"""

import json
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from epl_forecast.competitions import COMPETITIONS

LONDON = ZoneInfo("Europe/London")

FULL_SEASON = {c.competition_id: c.rounds for c in COMPETITIONS}
FULL_FIELD = {c.competition_id: c.teams for c in COMPETITIONS}
REGISTRIES = ("pl_adjustments.json", "efl_adjustments.json")


def reviewed_events(competition: str, season: str) -> list[dict]:
    """Every reviewed sanction for a season, dated or not."""
    events = []
    for name in REGISTRIES:
        path = Path(__file__).parent.joinpath("data", name)
        for event in json.loads(path.read_text()):
            if event["season_id"] == season and event["competition_id"] == competition:
                events.append(event)
    return events


def reviewed_adjustments(competition: str, season: str, as_of: date | None = None) -> list[dict]:
    """Reviewed sanctions a forecaster could have applied.

    An entry whose announcement date could not be established carries a null
    ``known_on`` and is never applied to a forecast; it still describes the club, so
    the derived final-table adjustment is not double counted against it.
    """
    return [
        event
        for event in reviewed_events(competition, season)
        if event["known_on"] is not None
        and (as_of is None or date.fromisoformat(event["known_on"]) <= as_of)
    ]


def _prefixes(matches, competition: str, season: str) -> dict[str, list[tuple[int, int]]]:
    """Cumulative (points, goal difference) after each of a team's matches, in order."""
    played: dict[str, list[tuple[int, int]]] = {}
    ordered = sorted(
        (
            match
            for match in matches
            if match.fixture.competition_id == competition and match.fixture.season_id == season
        ),
        key=lambda match: (match.fixture.match_date, match.fixture.match_id),
    )
    for match in ordered:
        for team, scored, conceded in (
            (match.fixture.home_team_id, match.home_goals, match.away_goals),
            (match.fixture.away_team_id, match.away_goals, match.home_goals),
        ):
            points, difference = played[team][-1] if played.get(team) else (0, 0)
            earned = 3 if scored > conceded else 1 if scored == conceded else 0
            played.setdefault(team, []).append((points + earned, difference + scored - conceded))
    return played


def derive(standings: list[dict], matches, competition: str, season: str) -> dict:
    """Compare one retained standings snapshot with the archived results it should match."""
    rows = [
        row
        for row in standings
        if row["competition_id"] == competition and row["season_id"] == season
    ]
    prefixes = _prefixes(matches, competition, season)
    adjustments, unknown = [], []
    for row in sorted(rows, key=lambda row: row["team_id"]):
        team = row["team_id"]
        history = prefixes.get(team, [])
        reported = row["played"]
        archived = (
            history[reported - 1]
            if 0 < reported <= len(history)
            else (0, 0)
            if not reported
            else None
        )
        if archived is None or archived[1] != row["goal_difference"]:
            unknown.append(
                {
                    "team_id": team,
                    "reported_played": reported,
                    "archived_played": len(history),
                    "reported_goal_difference": row["goal_difference"],
                    "archived_goal_difference": archived[1] if archived else None,
                    "resolution": "unknown: standings snapshot does not describe archived results",
                }
            )
            continue
        if row["points"] != archived[0]:
            adjustments.append(
                {
                    "competition_id": competition,
                    "season_id": season,
                    "team_id": team,
                    "points": row["points"] - archived[0],
                    "matches_covered": reported,
                    "observed_on": str(row["retrieved_at"].astimezone(LONDON).date()),
                    "evidence_basis": row["evidence_basis"],
                    "table_updated_on": (
                        str(row["updated_at"].astimezone(LONDON).date())
                        if row["updated_at"]
                        else None
                    ),
                    "source": f"api_football standings {row['source_sha256']}",
                    "basis": "derived from retained standings against archived results",
                }
            )
    complete = (
        len(rows) == FULL_FIELD[competition]
        and len({row["team_id"] for row in rows}) == FULL_FIELD[competition]
        and {row["team_id"] for row in rows} == set(prefixes)
        and not unknown
        and all(row["played"] == FULL_SEASON[competition] for row in rows)
    )
    return {
        "competition_id": competition,
        "season_id": season,
        "teams_reported": len(rows),
        "teams_unknown": len(unknown),
        "sanctioned_table_available": complete,
        "observed_on": min(
            (str(row["retrieved_at"].astimezone(LONDON).date()) for row in rows), default=None
        ),
        "adjustments": adjustments,
        "unknown": unknown,
    }


class SanctionRegistry:
    """Sanctioned tables for every retained season, derived once from one dataset."""

    def __init__(self, standings: list[dict], matches):
        self.derivations = {}
        for competition, season in sorted(
            {(row["competition_id"], row["season_id"]) for row in standings}
        ):
            derivation = derive(standings, matches, competition, season)
            self.derivations[competition, season] = derivation
            if derivation["sanctioned_table_available"]:
                self._check_reviewed(derivation)

    @staticmethod
    def _check_reviewed(derivation: dict) -> None:
        """A reviewed registry that contradicts a complete provider table is an error.

        The registry supplies announcement dates the provider does not publish, but its
        magnitudes are checkable: per club they must sum to the difference between the
        final table and the archived results.
        """
        competition, season = derivation["competition_id"], derivation["season_id"]
        derived = {a["team_id"]: a["points"] for a in derivation["adjustments"]}
        reviewed: dict[str, int] = {}
        for event in reviewed_events(competition, season):
            reviewed[event["team_id"]] = reviewed.get(event["team_id"], 0) + event["points"]
        if {k: v for k, v in reviewed.items() if v} != derived:
            raise ValueError(
                f"Reviewed sanctions disagree with the {competition} {season} final table: "
                f"reviewed {reviewed}, derived {derived}"
            )

    def derivation(self, competition: str, season: str) -> dict:
        return self.derivations.get(
            (competition, season),
            {
                "competition_id": competition,
                "season_id": season,
                "teams_reported": 0,
                "teams_unknown": 0,
                "sanctioned_table_available": False,
                "observed_on": None,
                "adjustments": [],
                "unknown": [],
            },
        )

    def final_adjustments(self, competition: str, season: str, cutoff: date) -> list[dict]:
        """Adjustments in force in the completed table, dated at the scoring cutoff.

        The provider does not retain announcement dates, so these carry the cutoff of
        the season they completed: a sanction present in the final table was in force
        by the end of that season, whatever day it was imposed.
        """
        derivation = self.derivation(competition, season)
        if not derivation["sanctioned_table_available"]:
            return []
        return [
            {**adjustment, "known_on": str(cutoff), "applies": "final sanctioned table"}
            for adjustment in derivation["adjustments"]
        ]

    def known_adjustments(self, competition: str, season: str, as_of: date) -> list[dict]:
        """Adjustments a forecaster could have applied at ``as_of``.

        A reviewed announcement date beats a retrieval date, and a team the reviewed
        registry already covers is left to it, so a mid-season sanction is not counted
        twice when the final table also shows it.

        A derived sanction is dated by its own observation only when that observation
        was captured live. A retrospective backfill says when this archive learned of a
        sanction, not when anyone could have; treating the two as the same would let a
        2026 capture inform a 2019 forecast or, read the other way, pretend a decision
        had no date at all. Live captures do carry availability: a sanction visible in
        today's table was in force when the table was published.
        """
        reviewed = [
            {**event, "applies": "reviewed announcement"}
            for event in reviewed_adjustments(competition, season, as_of)
        ]
        covered = {event["team_id"] for event in reviewed_events(competition, season)}
        derived = [
            {**adjustment, "known_on": adjustment["observed_on"], "applies": "observed standings"}
            for adjustment in self.derivation(competition, season)["adjustments"]
            if adjustment["team_id"] not in covered
            and adjustment["evidence_basis"] == "captured"
            and date.fromisoformat(adjustment["observed_on"]) <= as_of
        ]
        return reviewed + derived

    def audit(self) -> list[dict]:
        """One row per retained season, for surfacing unusable snapshots."""
        return [
            {
                "competition_id": derivation["competition_id"],
                "season_id": derivation["season_id"],
                "teams_reported": derivation["teams_reported"],
                "teams_unknown": derivation["teams_unknown"],
                "sanctioned_table_available": derivation["sanctioned_table_available"],
                "sanctioned_teams": len(derivation["adjustments"]),
                "derived_net_points": sum(a["points"] for a in derivation["adjustments"]),
                "reviewed_net_points": sum(
                    event["points"]
                    for event in reviewed_events(
                        derivation["competition_id"], derivation["season_id"]
                    )
                ),
                "reviewed_undated_events": sum(
                    event["known_on"] is None
                    for event in reviewed_events(
                        derivation["competition_id"], derivation["season_id"]
                    )
                ),
            }
            for derivation in self.derivations.values()
        ]


def load_registry(dataset) -> SanctionRegistry:
    return SanctionRegistry(dataset.rows("SELECT * FROM standings"), dataset.matches())


def load_sanctions(cutoff=None, store=None) -> SanctionRegistry:
    from epl_forecast.datasets import Dataset

    data = Dataset(cutoff, store=store)
    try:
        return load_registry(data)
    finally:
        data.close()
