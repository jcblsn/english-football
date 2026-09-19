from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import duckdb
import numpy as np
import pytest

from epl_forecast import cli, fit_state
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


def test_forecast_result_reuses_one_daily_fit_across_requested_cutoffs(
    tmp_path, small_history, monkeypatch
):
    config = tmp_path / "product.toml"
    config.write_text(
        """
competition_id = "eng-premier-league"
development_start = "2018-01-01"
development_end = "2018-02-01"
validation_start = "2018-02-01"
validation_end = "2018-03-01"
holdout_start = "2018-03-01"
holdout_end = "2018-04-01"
train_window_days = 10000
min_train_matches = 1

[[models]]
id = "test-model"
kind = "bayesian_xg_quality_tilt"

[models.parameters]
canonical_xg = true
""".strip()
        + "\n"
    )
    observations = xg_rows(small_history)

    class Data:
        data_revision = "snapshot-revision"

        def xg_observations(self):
            return observations

        def close(self):
            pass

    class Sanctions:
        def known_adjustments(self, *args):
            return []

    def live(cutoff, competition, season, data):
        return SimpleNamespace(
            observed_at=cutoff,
            competition_id=competition,
            season_id=season,
            remaining=[],
            details={},
            played=[],
            manifest={"requested_cutoff": cutoff.isoformat()},
        )

    monkeypatch.setattr(cli, "Dataset", lambda cutoff: Data())
    monkeypatch.setattr(cli, "load_live_season", live)
    monkeypatch.setattr(cli, "check_freshness", lambda *args: None)
    monkeypatch.setattr(cli, "load_dataset", lambda data: (small_history, [], {"batches": []}))
    monkeypatch.setattr(cli, "load_registry", lambda data: Sanctions())
    monkeypatch.setattr(cli, "current_adjustments", lambda *args: {})
    monkeypatch.setattr(cli, "build_forecast", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        "epl_forecast.results.write_forecast_result",
        lambda *args, **kwargs: {"result_id": kwargs["result_id"], "status": "written"},
    )
    arguments = SimpleNamespace(
        snapshot=None,
        snapshot_manifest=None,
        result_id="forecast-1",
        results=tmp_path / "results.duckdb",
        competition="eng-premier-league",
        season="2021-2022",
        max_snapshot_age_hours=24,
        config=config,
        model="test-model",
        fits=tmp_path / "fits.duckdb",
        europe_scenario=None,
        adjustments=None,
        market_pool=None,
        seed=1,
        simulations=100,
        max_goals=10,
        cutoff="2026-09-18T10:00:00+00:00",
    )
    _, first_run, _ = cli.forecast_result(arguments)
    arguments.cutoff = "2026-09-18T18:00:00+00:00"
    arguments.result_id = "forecast-2"
    _, second_run, _ = cli.forecast_result(arguments)

    assert first_run["fit_checkpoint"]["status"] == "fresh"
    assert second_run["fit_checkpoint"]["status"] == "exact"
    assert "data_cutoff" not in second_run["model"]["parameters"]
    with duckdb.connect(str(arguments.fits), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM fit_checkpoints").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM fit_uses").fetchone() == (2,)
        assert connection.execute(
            "SELECT count(DISTINCT requested_cutoff) FROM fit_uses"
        ).fetchone() == (2,)


def test_recaptured_provenance_does_not_block_semantic_prefix_resume(tmp_path, small_history):
    path = tmp_path / "fits.duckdb"
    spec = model_spec()
    first = [
        replace(match, source_sha256="a" * 64, source_row=index)
        for index, match in enumerate(small_history[:6])
    ]
    first_rows = [{**row, "source_sha256": "a" * 64} for row in xg_rows(first)]
    fitted_model_from_checkpoint(
        path,
        spec,
        first,
        first[-1].available_on,
        "revision-1",
        observations=first_rows,
        requested_cutoff=datetime(2026, 9, 18, 12, tzinfo=UTC),
    )
    recaptured = [
        replace(match, source_sha256="b" * 64, source_row=index + 100)
        for index, match in enumerate(small_history[:6])
    ]
    appended = [*recaptured, *small_history[6:]]
    appended_rows = [{**row, "source_sha256": "b" * 64} for row in xg_rows(appended)]
    resumed, _ = fitted_model_from_checkpoint(
        path,
        spec,
        appended,
        appended[-1].available_on,
        "revision-2",
        observations=appended_rows,
        requested_cutoff=datetime(2026, 9, 19, 12, tzinfo=UTC),
    )
    fresh, _ = fitted_model_from_checkpoint(
        tmp_path / "fresh.duckdb",
        spec,
        appended,
        appended[-1].available_on,
        "revision-2",
        observations=appended_rows,
    )
    assert resumed.fit_state_status == "resumed"
    for actual, expected in zip(resumed.members, fresh.members, strict=True):
        np.testing.assert_allclose(actual.mean, expected.mean, atol=1e-11)
        np.testing.assert_allclose(actual.covariance, expected.covariance, atol=1e-11)
    with duckdb.connect(str(path), read_only=True) as connection:
        assert connection.execute(
            "SELECT count(DISTINCT capture_provenance_sha256) FROM fit_uses"
        ).fetchone() == (2,)


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
