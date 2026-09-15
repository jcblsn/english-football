import copy
import json
from datetime import date, datetime, timedelta

import pytest
from test_publication import Store, sample_forecast

from epl_forecast import hindcast
from epl_forecast.hindcast import (
    INDEX_KEY,
    SEED,
    claim_edition,
    derive_hindcast,
    document_key,
    hindcast_id,
    private_key,
    publish_index,
    publish_origin,
    publish_season,
    run_hindcasts,
    simulate_origin,
    weekly_origins,
)
from epl_forecast.live import LONDON
from epl_forecast.models.baselines import AttackDefensePoisson
from epl_forecast.publication import (
    check_publishable,
    derive_forecast,
    document_kind,
    load_policy,
    materialize_publication,
    publish_documents,
)
from epl_forecast.record import update_record

NAMES = {"arsenal": "Arsenal", "chelsea": "Chelsea"}


def record(identifier, origin, cutoff, title=0.5):
    simulation = copy.deepcopy(sample_forecast()["simulation"])
    simulation.update(played_matches=6, remaining_matches=374, state_uncertainty="posterior")
    simulation["teams"][0]["title_probability"] = title
    simulation["teams"][1]["title_probability"] = 1 - title
    return {
        "model_version": "v0.0",
        "competition_id": "eng-premier-league",
        "season_id": "2021-2022",
        "hindcast_id": identifier,
        "origin_at": origin,
        "model_results_cutoff": cutoff,
        "simulations": 10000,
        "seed": SEED,
        "adjustments": [],
        "simulation": simulation,
    }


def season_records():
    return [
        record("2021-08-09T080000Z", "2021-08-09T09:00:00+01:00", "2021-08-09", 0.5),
        record("2021-08-16T080000Z", "2021-08-16T09:00:00+01:00", "2021-08-16", 0.5),
        record("2021-08-23T080000Z", "2021-08-23T09:00:00+01:00", "2021-08-23", 0.7),
    ]


def test_weekly_origins_are_mondays_at_nine_in_london_until_every_result_is_known():
    origins = weekly_origins(date(2021, 8, 13), date(2022, 5, 22))
    assert origins[0] == datetime(2021, 8, 9, 9, tzinfo=LONDON)
    assert origins[-1] == datetime(2022, 5, 23, 9, tzinfo=LONDON)
    assert all(origin.weekday() == 0 and origin.hour == 9 for origin in origins)
    assert all(b - a == timedelta(days=7) for a, b in zip(origins, origins[1:], strict=False))
    assert hindcast_id(origins[0]) == "2021-08-09T080000Z"
    assert "2021-11-01T090000Z" in {hindcast_id(origin) for origin in origins}
    assert weekly_origins(date(2021, 8, 9), date(2022, 5, 23))[-1].date() == date(2022, 5, 30)


def test_a_hindcast_document_is_retrospective_and_sanitized():
    policy = load_policy()
    document = derive_hindcast(season_records()[0], NAMES)
    check_publishable(document, policy)
    assert document_kind(document) == "hindcast"
    assert document["retrospective"] is True
    assert document["model"] == {"version": "v0.0"}
    assert document["teams"][0]["events"]["title_probability"] == 0.5
    text = json.dumps(document)
    for private in ("seed", "adjustments", "M7", "sha256"):
        assert private not in text
    with pytest.raises(ValueError, match="not in the forecast contract"):
        check_publishable(document, policy, "forecast")


def test_hindcasts_cannot_enter_live_pointers_or_the_record():
    policy = load_policy()
    store = Store()
    document = derive_hindcast(season_records()[0], NAMES)
    with pytest.raises(ValueError, match="live forecast pointers"):
        publish_documents(store, [document], policy)
    assert store.objects == {}
    with pytest.raises(ValueError, match="prospective record"):
        update_record(None, [document], {}, policy)
    live = publish_documents(
        store, [derive_forecast(sample_forecast(), "2026-09-10T120000Z")], policy
    )
    pointer = {**live["forecasts"][0], "href": document_key(season_records()[0])}
    with pytest.raises(ValueError, match="only link under forecasts/"):
        check_publishable({**live, "forecasts": [pointer]}, policy, "current")
    archive = store.objects["forecasts/eng-premier-league/archive.json"]
    with pytest.raises(ValueError, match="only link under forecasts/"):
        check_publishable({**archive, "forecasts": [pointer]}, policy, "archive")


def test_the_series_keeps_every_weekly_origin_and_materializes_only_on_request(tmp_path):
    policy = load_policy()
    data_store, publish_store = Store(), Store()
    records = season_records()
    for item in reversed(records):
        publish_origin(item, NAMES, policy, data_store, publish_store)
    assert private_key(records[0]) in data_store.objects
    entry = publish_season(publish_store, records, policy)
    series = publish_store.objects[entry["href"]]
    assert document_kind(series) == "hindcast_series"
    assert entry["href"] == "hindcasts/v0.0/eng-premier-league/2021-2022/series.json"
    assert [origin["hindcast_id"] for origin in series["origins"]] == [
        item["hindcast_id"] for item in records
    ]
    arsenal = next(team for team in series["teams"] if team["team_id"] == "arsenal")
    assert arsenal["events"]["title_probability"] == [0.5, 0.5, 0.7]
    assert arsenal["mean_points"] == [80.5, 80.5, 80.5]
    assert arsenal["current_points"] == [9, 9, 9]
    index = publish_index(publish_store, [entry], policy)
    assert document_kind(index) == "hindcast_index"
    assert index["seasons"] == [entry]
    assert publish_index(publish_store, [entry], policy) is publish_store.objects[INDEX_KEY]

    publish_documents(
        publish_store, [derive_forecast(sample_forecast(), "2026-09-10T120000Z")], policy
    )
    assert materialize_publication(publish_store, tmp_path)["hindcasts"] == 0
    assert not (tmp_path / "data/hindcasts").exists()
    assert materialize_publication(publish_store, tmp_path, hindcasts=True)["hindcasts"] == 3
    assert (tmp_path / "data" / INDEX_KEY).exists()
    assert json.loads((tmp_path / "data" / entry["href"]).read_text()) == series
    current = json.loads((tmp_path / "data/current.json").read_text())
    assert all(row["href"].startswith("forecasts/") for row in current["forecasts"])


def test_a_series_needs_every_weekly_document():
    policy = load_policy()
    publish_store = Store()
    records = season_records()
    publish_origin(records[0], NAMES, policy, Store(), publish_store)
    with pytest.raises(ValueError, match="must exist before its series"):
        publish_season(publish_store, records, policy)


def test_an_edition_refuses_a_changed_model():
    store = Store()
    manifest = {"model_version": "v0.0", "model_code": {"model.py": "a"}, "simulations": 10000}
    claim_edition(store, manifest)
    claim_edition(store, dict(manifest))
    with pytest.raises(ValueError, match="different model"):
        claim_edition(store, {**manifest, "model_code": {"model.py": "b"}})


def test_hindcasts_refuse_a_local_workspace_with_contents(tmp_path):
    (tmp_path / "manifests").mkdir()
    (tmp_path / "manifests/old.json").write_text("{}")
    with pytest.raises(ValueError, match="must be empty"):
        run_hindcasts(Store(), Store(), tmp_path)


def test_an_origin_uses_only_results_available_on_its_day(full_season, monkeypatch):
    def fitted(matches, config, model_id, as_of):
        training = [m for m in matches if m.available_on <= as_of]
        return AttackDefensePoisson().fit(training, as_of), {}, training

    monkeypatch.setattr(hindcast, "fitted_model", fitted)
    hindcast._initialize(full_season, [])
    task = {
        "model_version": "v0.0",
        "competition_id": "eng-premier-league",
        "season_id": "2020-2021",
        "hindcast_id": "2020-08-17T080000Z",
        "origin_at": "2020-08-17T09:00:00+01:00",
        "model_results_cutoff": "2020-08-17",
        "simulations": 20,
        "seed": SEED,
        "adjustments": [],
    }
    result = simulate_origin(task)
    simulation = result["simulation"]
    assert simulation["played_matches"] == 160
    assert result["training_matches"] == 160
    assert "match_frequencies" not in simulation
    assert all("goal_difference_distribution" not in row for row in simulation["teams"])
    assert sum(row["played"] for row in simulation["teams"]) == 320
