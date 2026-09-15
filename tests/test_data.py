from datetime import date

import pytest

from epl_forecast.data.football_data import normalize_rows, parse_date
from epl_forecast.data.sources import source_url
from epl_forecast.storage import sha256_bytes

HEADER = "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365H,B365D,B365A\n"
VALID = "E0,02/09/2020,Arsenal,Chelsea,0,1,A,2.4,3.5,2.9\n"


def entry(payload):
    digest = sha256_bytes(payload)
    return {
        "season_start": 2020,
        "season_id": "2020-2021",
        "division": "E0",
        "competition_id": "eng-premier-league",
        "sha256": digest,
        "url": "https://football-data.co.uk/mmz4281/2021/E0.csv",
        "path": f"raw/football_data/2020-2021/E0/{digest}.csv",
    }


def normalize(text):
    payload = text.encode()
    return normalize_rows(payload, entry(payload), {"Arsenal": "arsenal", "Chelsea": "chelsea"})


def test_dates_availability_and_provenance():
    matches, odds, audit = normalize(HEADER + VALID)
    match = matches[0]
    assert match.fixture.match_date == date(2020, 9, 2)
    assert match.available_on == date(2020, 9, 3)
    assert parse_date("02/09/20") == match.fixture.match_date
    assert match.source_row == 2
    assert match.source_sha256 == sha256_bytes((HEADER + VALID).encode())
    assert match.source_time == ""
    assert odds[0]["observed_at"] == ""
    assert not audit["complete"]


def test_national_league_has_a_historical_result_source():
    assert source_url(2025, "EC") == "https://football-data.co.uk/mmz4281/2526/EC.csv"


@pytest.mark.parametrize(
    "bad",
    [
        VALID.replace(",0,1,A,", ",-1,1,A,"),
        VALID.replace(",0,1,A,", ",,1,A,"),
        VALID.replace(",0,1,A,", ",0,1,H,"),
        VALID.replace("Arsenal", "Unknown"),
        VALID.replace("02/09/2020", "02/09/2025"),
        VALID.replace("Chelsea", "Arsenal"),
    ],
)
def test_invalid_core_data_rejected(bad):
    with pytest.raises(ValueError):
        normalize(HEADER + bad)


def test_duplicate_pair_rejected_even_if_date_changes():
    with pytest.raises(ValueError, match="Duplicate"):
        normalize(HEADER + VALID + VALID.replace("02/09", "03/09"))


@pytest.mark.parametrize("price", ["1", "0", "nan", "inf", "broken"])
def test_bad_odds_are_audited_without_losing_the_result(price):
    matches, odds, audit = normalize(HEADER + VALID.replace("2.4", price))
    assert len(matches) == 1
    assert odds == []
    assert audit["odds"]["bet365_preclosing"]["invalid"] == 1
