from dataclasses import replace
from datetime import timedelta

import duckdb
import numpy as np
import pytest

from epl_forecast.fit_state import (
    fitted_model_from_checkpoint,
    load_fit_checkpoint,
)


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


def test_irrelevant_revision_reuses_and_model_inputs_invalidate(tmp_path, small_history):
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
