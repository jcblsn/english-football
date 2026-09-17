from datetime import date, timedelta

import pytest

from epl_forecast.schema import Fixture, Match, fixture_id


def match_on(day: date, home: str, away: str, hg: int, ag: int, season="2020-2021") -> Match:
    competition = "eng-premier-league"
    fixture = Fixture(
        fixture_id(competition, season, home, away), competition, season, day, home, away
    )
    return Match(fixture, hg, ag)


@pytest.fixture(autouse=True)
def no_r2_environment(monkeypatch):
    """Tests use fake stores; a developer shell with R2 settings must not reach the real buckets."""
    for name in (
        "R2_ACCOUNT_ID",
        "R2_DATA_BUCKET",
        "R2_PUBLISH_BUCKET",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def small_history():
    teams = ["a", "b", "c", "d"]
    pairs = [(h, a) for h in teams for a in teams if h != a]
    return [
        match_on(date(2020, 8, 1) + timedelta(days=i), h, a, i % 4, i % 3)
        for i, (h, a) in enumerate(pairs)
    ]


@pytest.fixture
def full_season():
    teams = [f"team-{i:02d}" for i in range(20)]
    pairs = [(h, a) for h in teams for a in teams if h != a]
    return [
        match_on(date(2020, 8, 1) + timedelta(days=i // 10), h, a, 1, 0)
        for i, (h, a) in enumerate(pairs)
    ]
