from dataclasses import replace
from datetime import date, timedelta

import duckdb
import numpy as np
import pytest

from epl_forecast import fit_state
from epl_forecast.fit_state import (
    fitted_model_from_checkpoint,
    load_fit_checkpoint,
)
from epl_forecast.schema import Fixture, Match, fixture_id


def xg_rows(matches):
    return [
        {
            "match_id": match.fixture.match_id,
            "match_date": str(match.fixture.match_date),
            "available_on": str(match.available_on),
            "home_goals": match.home_goals,
            "away_goals": match.away_goals,
            "home_xg": 1.5,
            "away_xg": 0.8,
        }
        for match in matches
    ]


def model_spec():
    return {
        "id": "test-model",
        "kind": "bayesian_xg_quality_tilt",
        "parameters": {
            "canonical_xg": True,
            "competition_id": "eng-premier-league",
        },
    }


def test_checkpoint_restores_exact_m10_state(tmp_path, small_history):
    path = tmp_path / "fits.duckdb"
    cutoff = small_history[-1].available_on
    rows = xg_rows(small_history)
    fitted, reused = fitted_model_from_checkpoint(
        path,
        model_spec(),
        small_history,
        cutoff,
        "revision-1",
        observations=rows,
    )
    restored, reused_again = fitted_model_from_checkpoint(
        path,
        model_spec(),
        small_history,
        cutoff,
        "revision-1",
        observations=rows,
    )
    assert not reused
    assert reused_again
    np.testing.assert_array_equal(restored.weights, fitted.weights)
    for actual, expected in zip(restored.members, fitted.members, strict=True):
        np.testing.assert_array_equal(actual.mean, expected.mean)
        np.testing.assert_array_equal(actual.covariance, expected.covariance)
        assert actual.team_index == expected.team_index
        assert actual.entry_priors.keys() == expected.entry_priors.keys()
        assert actual.fit_diagnostics == expected.fit_diagnostics
    fixture = replace(
        small_history[0].fixture,
        match_date=cutoff + timedelta(days=20),
    )
    np.testing.assert_array_equal(
        restored.predict_match(fixture).probabilities,
        fitted.predict_match(fixture).probabilities,
    )
    with duckdb.connect(str(path), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM fit_checkpoints").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM fit_members").fetchone()[0] == 3


def test_irrelevant_revision_reuses_and_model_inputs_invalidate(
    tmp_path, small_history, monkeypatch
):
    path = tmp_path / "fits.duckdb"
    cutoff = small_history[-1].available_on
    spec = model_spec()
    rows = xg_rows(small_history)
    fitted_model_from_checkpoint(path, spec, small_history, cutoff, "revision-1", observations=rows)
    assert load_fit_checkpoint(
        path,
        spec,
        small_history,
        cutoff,
        "revision-2",
        observations=rows,
    )
    changed_xg = [{**row, "home_xg": 2.0} if index == 0 else row for index, row in enumerate(rows)]
    assert (
        load_fit_checkpoint(
            path,
            spec,
            small_history,
            cutoff,
            "revision-1",
            observations=changed_xg,
        )
        is None
    )
    monkeypatch.setattr(fit_state, "fit_protocol_identity", lambda: "changed-normalization")
    assert (
        load_fit_checkpoint(
            path,
            spec,
            small_history,
            cutoff,
            "revision-1",
            observations=rows,
        )
        is None
    )
    corrected = [*small_history[:-1], replace(small_history[-1], home_goals=4)]
    assert (
        load_fit_checkpoint(
            path,
            spec,
            corrected,
            cutoff,
            "revision-1",
            observations=rows,
        )
        is None
    )


def test_incomplete_checkpoint_is_rejected(tmp_path, small_history):
    path = tmp_path / "fits.duckdb"
    cutoff = small_history[-1].available_on
    spec = model_spec()
    rows = xg_rows(small_history)
    fitted_model_from_checkpoint(path, spec, small_history, cutoff, "revision-1", observations=rows)
    with duckdb.connect(str(path)) as connection:
        connection.execute("DELETE FROM fit_members WHERE member_index = 2")
    with pytest.raises(ValueError, match="incomplete member state"):
        load_fit_checkpoint(
            path,
            spec,
            small_history,
            cutoff,
            "revision-1",
            observations=rows,
        )


def test_checkpoint_resumes_only_at_complete_day_boundary(tmp_path, small_history):
    path = tmp_path / "fits.duckdb"
    spec = model_spec()
    rows = xg_rows(small_history)
    first = small_history[:6]
    fitted_model_from_checkpoint(
        path, spec, first, first[-1].available_on, "revision-1", observations=rows
    )
    resumed, reused = fitted_model_from_checkpoint(
        path,
        spec,
        small_history,
        small_history[-1].available_on,
        "revision-2",
        observations=rows,
    )
    fresh_path = tmp_path / "fresh.duckdb"
    fresh, _ = fitted_model_from_checkpoint(
        fresh_path,
        spec,
        small_history,
        small_history[-1].available_on,
        "revision-2",
        observations=rows,
    )
    assert not reused
    assert resumed.fit_state_status == "resumed"
    for actual, expected in zip(resumed.members, fresh.members, strict=True):
        np.testing.assert_allclose(actual.mean, expected.mean, atol=1e-11)
        np.testing.assert_allclose(actual.covariance, expected.covariance, atol=1e-11)

    same_day = [
        *small_history[:6],
        replace(
            small_history[6],
            fixture=replace(
                small_history[6].fixture,
                match_date=small_history[5].fixture.match_date,
            ),
        ),
    ]
    same_day_rows = xg_rows(same_day)
    same_day_model, _ = fitted_model_from_checkpoint(
        path,
        spec,
        same_day,
        same_day[-1].available_on,
        "revision-3",
        observations=same_day_rows,
    )
    assert same_day_model.fit_state_status == "fresh"


def test_season_boundary_resume_matches_fresh_fit(tmp_path, small_history):
    path = tmp_path / "fits.duckdb"
    spec = model_spec()
    first_rows = xg_rows(small_history)
    fitted_model_from_checkpoint(
        path,
        spec,
        small_history,
        small_history[-1].available_on,
        "revision-1",
        observations=first_rows,
    )
    competition = "eng-premier-league"
    fixture = Fixture(
        fixture_id(competition, "2021-2022", "a", "b"),
        competition,
        "2021-2022",
        date(2021, 8, 1),
        "a",
        "b",
    )
    history = [*small_history, Match(fixture, 2, 1)]
    rows = xg_rows(history)
    resumed, _ = fitted_model_from_checkpoint(
        path,
        spec,
        history,
        history[-1].available_on,
        "revision-2",
        observations=rows,
    )
    fresh, _ = fitted_model_from_checkpoint(
        tmp_path / "fresh.duckdb",
        spec,
        history,
        history[-1].available_on,
        "revision-2",
        observations=rows,
    )
    assert resumed.fit_state_status == "resumed"
    for actual, expected in zip(resumed.members, fresh.members, strict=True):
        np.testing.assert_allclose(actual.mean, expected.mean, atol=1e-11)
        np.testing.assert_allclose(actual.covariance, expected.covariance, atol=1e-11)


def test_training_window_and_late_xg_force_fresh_fit(tmp_path, small_history):
    spec = model_spec()
    rows = xg_rows(small_history)
    window_path = tmp_path / "window.duckdb"
    fitted_model_from_checkpoint(
        window_path,
        spec,
        small_history,
        small_history[-1].available_on,
        "revision-1",
        observations=rows,
    )
    window = small_history[2:]
    changed_window, _ = fitted_model_from_checkpoint(
        window_path,
        spec,
        window,
        window[-1].available_on,
        "revision-2",
        observations=rows,
    )
    assert changed_window.fit_state_status == "fresh"

    xg_path = tmp_path / "late-xg.duckdb"
    fitted_model_from_checkpoint(
        xg_path,
        spec,
        small_history,
        small_history[-1].available_on,
        "revision-1",
        observations=rows[1:],
    )
    late_xg, _ = fitted_model_from_checkpoint(
        xg_path,
        spec,
        small_history,
        small_history[-1].available_on,
        "revision-2",
        observations=rows,
    )
    assert late_xg.fit_state_status == "fresh"


def test_changed_source_competition_entry_evidence_matches_a_fresh_fit(tmp_path, small_history):
    source_fixture = replace(
        small_history[0].fixture,
        match_id=fixture_id("eng-national-league", "2020-2021", "a", "b"),
        competition_id="eng-national-league",
        season_id="2020-2021",
    )
    history = [replace(small_history[0], fixture=source_fixture), *small_history[1:]]
    rows = xg_rows(history)
    checkpoint = tmp_path / "entry-evidence.duckdb"
    fitted_model_from_checkpoint(
        checkpoint,
        model_spec(),
        history,
        history[-1].available_on,
        "revision-1",
        observations=rows,
    )
    corrected = [replace(history[0], home_goals=4), *history[1:]]
    corrected_rows = xg_rows(corrected)
    replayed, _ = fitted_model_from_checkpoint(
        checkpoint,
        model_spec(),
        corrected,
        corrected[-1].available_on,
        "revision-2",
        observations=corrected_rows,
    )
    fresh, _ = fitted_model_from_checkpoint(
        tmp_path / "fresh-entry-evidence.duckdb",
        model_spec(),
        corrected,
        corrected[-1].available_on,
        "revision-2",
        observations=corrected_rows,
    )
    assert replayed.fit_state_status == "fresh"
    for actual, expected in zip(replayed.members, fresh.members, strict=True):
        np.testing.assert_allclose(actual.mean, expected.mean, atol=1e-11)
        np.testing.assert_allclose(actual.covariance, expected.covariance, atol=1e-11)
