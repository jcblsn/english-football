from epl_forecast.competitions import (
    COMPETITION_IDS,
    ENTRY_SOURCE_COMPETITION_IDS,
    competition,
    entry_source_team_count,
)


def test_national_league_is_a_source_and_not_a_forecast_competition():
    assert "eng-national-league" in ENTRY_SOURCE_COMPETITION_IDS
    assert "eng-national-league" not in COMPETITION_IDS
    assert len(COMPETITION_IDS) == 4


def test_national_league_cannot_be_selected_as_a_product_competition():
    try:
        competition("eng-national-league")
    except ValueError as error:
        assert str(error) == "Unsupported competition: eng-national-league"
    else:
        raise AssertionError("National League was accepted as a product competition")


def test_reviewed_national_league_field_size_exceptions_are_explicit():
    assert entry_source_team_count("eng-national-league", "2019-2020") == 24
    assert entry_source_team_count("eng-national-league", "2020-2021") == 23
    assert entry_source_team_count("eng-national-league", "2021-2022") == 23
    assert entry_source_team_count("eng-national-league", "2022-2023") == 24
