"""The English league divisions the product forecasts, in pyramid order."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Competition:
    competition_id: str
    name: str
    tier: int
    teams: int
    football_data_division: str
    api_football_league: int | None

    @property
    def matches(self) -> int:
        return self.teams * (self.teams - 1)

    @property
    def rounds(self) -> int:
        return 2 * (self.teams - 1)


FORECAST_COMPETITIONS = (
    Competition("eng-premier-league", "Premier League", 1, 20, "E0", 39),
    Competition("eng-championship", "Championship", 2, 24, "E1", 40),
    Competition("eng-league-one", "League One", 3, 24, "E2", 41),
    Competition("eng-league-two", "League Two", 4, 24, "E3", 42),
)
NATIONAL_LEAGUE = Competition("eng-national-league", "National League", 5, 24, "EC", None)
ENTRY_SOURCE_COMPETITIONS = (*FORECAST_COMPETITIONS, NATIONAL_LEAGUE)
COMPETITIONS = FORECAST_COMPETITIONS
COMPETITION_IDS = tuple(c.competition_id for c in FORECAST_COMPETITIONS)
ENTRY_SOURCE_COMPETITION_IDS = tuple(c.competition_id for c in ENTRY_SOURCE_COMPETITIONS)
_BY_ID = {c.competition_id: c for c in FORECAST_COMPETITIONS}
_ENTRY_SOURCE_BY_ID = {c.competition_id: c for c in ENTRY_SOURCE_COMPETITIONS}
_TEAM_COUNT_EXCEPTIONS = {
    ("eng-national-league", "2020-2021"): 23,
    ("eng-national-league", "2021-2022"): 23,
}


def competition(competition_id: str) -> Competition:
    try:
        return _BY_ID[competition_id]
    except KeyError:
        raise ValueError(f"Unsupported competition: {competition_id}") from None


def entry_source_team_count(competition_id: str, season_id: str) -> int:
    try:
        return _TEAM_COUNT_EXCEPTIONS.get(
            (competition_id, season_id), _ENTRY_SOURCE_BY_ID[competition_id].teams
        )
    except KeyError:
        raise ValueError(f"Unsupported entry source: {competition_id}") from None


def adjacent(competition_id: str, step: int) -> Competition | None:
    """The modeled division `step` tiers below (positive) or above (negative), if any."""
    tier = competition(competition_id).tier + step
    return next((c for c in COMPETITIONS if c.tier == tier), None)
