from datetime import date

import pytest

from epl_forecast.data.football_data import normalize_rows, parse_date
from epl_forecast.data.sources import csv_rows, source_url
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


def test_football_data_accepts_retained_windows_names():
    _, rows = csv_rows(
        "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\nEC,01/08/2010,King’s Lynn,York,1,0,H\n".encode(
            "cp1252"
        )
    )
    assert rows[0][1]["HomeTeam"] == "King’s Lynn"


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


def xg_row(match_id, match_date, provider):
    return {
        "match_id": match_id,
        "match_date": match_date,
        "home_xg": 1.0,
        "away_xg": 1.0,
        "provider": provider,
    }


def test_api_football_xg_replaces_understat_from_its_first_match_date():
    from epl_forecast.datasets import select_xg_observations

    understat = [
        xg_row("eng-premier-league:2022-2023:a:b", "2022-08-06", "understat"),
        xg_row("eng-premier-league:2022-2023:c:d", "2023-01-20", "understat"),
        xg_row("eng-premier-league:2026-2027:e:f", "2026-08-20", "understat"),
    ]
    api = [
        xg_row("eng-premier-league:2022-2023:g:h", "2023-01-18", "api_football"),
        xg_row("eng-championship:2023-2024:i:j", "2023-08-04", "api_football"),
    ]
    selected = select_xg_observations(understat, api)
    assert [row["match_id"] for row in selected] == [
        "eng-premier-league:2022-2023:a:b",
        "eng-premier-league:2022-2023:g:h",
        "eng-championship:2023-2024:i:j",
    ]


def test_understat_stays_where_a_competition_has_no_api_football_xg():
    from epl_forecast.datasets import select_xg_observations

    understat = [xg_row("eng-premier-league:2025-2026:a:b", "2025-08-16", "understat")]
    assert select_xg_observations(understat, []) == understat
