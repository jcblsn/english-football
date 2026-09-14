import json
from pathlib import Path

import pytest

from epl_forecast.datawrapper import DatawrapperError, chart_data, load_api_key, publish


class Client:
    def __init__(self):
        self.calls = []

    def create_chart(self, title):
        self.calls.append(("create", title))
        return {"id": "Ab123"}

    def update_chart(self, chart_id, properties):
        self.calls.append(("update", chart_id, properties))
        return properties

    def upload_data(self, chart_id, data):
        self.calls.append(("upload", chart_id, data))

    def publish_chart(self, chart_id):
        self.calls.append(("publish", chart_id))
        return {"url": f"//datawrapper.dwcdn.net/{chart_id}/1/"}


def forecast():
    return {
        "snapshot_id": "2026-09-13T193232Z",
        "generated_at": "2026-09-13T19:33:15+00:00",
        "season_id": "2026-2027",
        "simulations": 20000,
        "teams": [
            {"name": "Second", "events": {"title_probability": 0.25}},
            {"name": "First", "events": {"title_probability": 0.75}},
        ],
    }


def site(root: Path):
    data = root / "data"
    document = data / "forecasts/latest/eng-premier-league.json"
    document.parent.mkdir(parents=True)
    document.write_text(json.dumps(forecast()))
    (data / "index.json").write_text(
        json.dumps(
            {
                "snapshots": [
                    {
                        "competitions": [
                            {
                                "competition_id": "eng-premier-league",
                                "href": "forecasts/latest/eng-premier-league.json",
                            }
                        ]
                    }
                ]
            }
        )
    )


def test_api_key_must_be_in_env_file(tmp_path):
    with pytest.raises(DatawrapperError, match="needs.*DATAWRAPPER_API_KEY"):
        load_api_key(tmp_path / ".env")
    env = tmp_path / ".env"
    env.write_text("OTHER=value\nDATAWRAPPER_API_KEY='secret'\n")
    assert load_api_key(env) == "secret"


def test_chart_data_ranks_real_probabilities():
    assert chart_data(forecast()) == "Club,Chance\nFirst,0.75\nSecond,0.25\n"


def test_publish_creates_once_then_updates_the_same_chart(tmp_path):
    site(tmp_path / "site")
    config = tmp_path / "datawrapper_poc.toml"
    config.write_text('chart_id = ""\n')
    client = Client()

    first = publish(tmp_path / "site", config, client=client)
    second = publish(tmp_path / "site", config, client=client)

    assert first == {
        "action": "created",
        "chart_id": "Ab123",
        "url": "https://datawrapper.dwcdn.net/Ab123/1/",
        "snapshot_id": "2026-09-13T193232Z",
    }
    assert second["action"] == "updated"
    assert config.read_text() == 'chart_id = "Ab123"\n'
    assert [call[0] for call in client.calls] == [
        "create",
        "update",
        "upload",
        "publish",
        "update",
        "upload",
        "publish",
    ]
