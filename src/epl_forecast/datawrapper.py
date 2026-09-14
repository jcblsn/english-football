"""Run the temporary Page 324 Datawrapper proof of concept."""

import csv
import io
import json
import re
import tomllib
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_ROOT = "https://api.datawrapper.de/v3"
CHART_ID = re.compile(r"^[A-Za-z0-9]{5}$")


class DatawrapperError(RuntimeError):
    pass


def load_api_key(env_path: Path = Path(".env")) -> str:
    if not env_path.is_file():
        raise DatawrapperError(f"Datawrapper needs {env_path} with DATAWRAPPER_API_KEY")
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        name, separator, value = line.partition("=")
        if separator and name.strip() == "DATAWRAPPER_API_KEY":
            key = value.strip().strip("\"'")
            if key:
                return key
    raise DatawrapperError(f"Datawrapper needs DATAWRAPPER_API_KEY in {env_path}")


class DatawrapperClient:
    def __init__(self, api_key: str, opener=urlopen):
        self.api_key = api_key
        self.opener = opener

    def request(self, method: str, endpoint: str, body=None, content_type=None, expected=(200,)):
        data = body
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "page-324/0.1",
        }
        if isinstance(body, dict):
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        elif isinstance(body, str):
            data = body.encode()
            headers["Content-Type"] = content_type or "text/plain"
        request = Request(f"{API_ROOT}{endpoint}", data=data, headers=headers, method=method)
        try:
            with self.opener(request, timeout=45) as response:
                status = response.status
                payload = response.read()
        except HTTPError as error:
            detail = error.read().decode(errors="replace").strip()
            suffix = f": {detail[:500]}" if detail else ""
            raise DatawrapperError(
                f"Datawrapper API returned HTTP {error.code} for {endpoint}{suffix}"
            ) from None
        except (URLError, TimeoutError) as error:
            raise DatawrapperError(
                f"Datawrapper API request failed: {type(error).__name__}"
            ) from None
        if status not in expected:
            raise DatawrapperError(
                f"Datawrapper API returned unexpected HTTP {status} for {endpoint}"
            )
        if not payload:
            return None
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            raise DatawrapperError("Datawrapper API returned invalid JSON") from None

    def create_chart(self, title: str) -> dict:
        return self.request(
            "POST",
            "/charts",
            {"title": title, "type": "d3-bars", "language": "en-GB"},
            expected=(200, 201),
        )

    def update_chart(self, chart_id: str, properties: dict) -> dict:
        return self.request("PATCH", f"/charts/{chart_id}", properties, expected=(200, 201))

    def upload_data(self, chart_id: str, data: str) -> None:
        self.request(
            "PUT",
            f"/charts/{chart_id}/data",
            data,
            content_type="text/csv; charset=utf-8",
            expected=(204,),
        )

    def publish_chart(self, chart_id: str) -> dict:
        return self.request("POST", f"/charts/{chart_id}/publish", {}, expected=(200, 201))


def load_chart_id(config_path: Path) -> str:
    with config_path.open("rb") as stream:
        chart_id = tomllib.load(stream).get("chart_id", "")
    if chart_id and not CHART_ID.fullmatch(chart_id):
        raise DatawrapperError(f"Invalid chart_id in {config_path}")
    return chart_id


def save_chart_id(config_path: Path, chart_id: str) -> None:
    if not CHART_ID.fullmatch(chart_id):
        raise DatawrapperError("Datawrapper returned an invalid chart ID")
    text = config_path.read_text()
    updated, count = re.subn(
        r'^chart_id[ \t]*=[ \t]*"[^"]*"[ \t]*$',
        f'chart_id = "{chart_id}"',
        text,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise DatawrapperError(f"Expected one chart_id setting in {config_path}")
    temporary = config_path.with_suffix(f"{config_path.suffix}.tmp")
    temporary.write_text(updated)
    temporary.replace(config_path)


def latest_forecast(site: Path) -> dict:
    data_root = site / "data"
    index = json.loads((data_root / "index.json").read_text())
    for snapshot in index["snapshots"]:
        for competition in snapshot["competitions"]:
            if competition["competition_id"] == "eng-premier-league":
                return json.loads((data_root / competition["href"]).read_text())
    raise DatawrapperError("The site index has no Premier League forecast")


def chart_data(forecast: dict) -> str:
    rows = sorted(
        (
            (team["name"], Decimal(str(team["events"]["title_probability"])) * 100)
            for team in forecast["teams"]
        ),
        key=lambda row: (-row[1], row[0]),
    )
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["Club", "Chance"])
    writer.writerows(
        (name, format(value, "f").rstrip("0").rstrip(".") or "0") for name, value in rows
    )
    return output.getvalue()


def chart_properties(forecast: dict) -> dict:
    generated_date = forecast["generated_at"][:10]
    season = forecast["season_id"].replace("-", "–")
    return {
        "title": "Who will win the Premier League?",
        "type": "d3-bars",
        "language": "en-GB",
        "metadata": {
            "axes": {"bars": "Chance"},
            "data": {"horizontal-header": True, "vertical-header": True},
            "describe": {
                "intro": f"The M7 model estimates each club's chance of winning the {season} Premier League.",
                "byline": "Page 324",
                "source-name": "Page 324 forecast",
                "source-url": "",
                "number-format": "0.[00]%",
            },
            "annotate": {
                "notes": f"Forecast from {generated_date}. Based on {forecast['simulations']:,} simulated seasons."
            },
            "visualize": {
                "resort-bars": True,
                "sort-asc": False,
                "value-label-format": "0.[00]%",
                "value-label-visibility": "show",
            },
        },
    }


def public_url(response: dict, chart_id: str) -> str:
    candidates = [
        response.get("publicUrl"),
        response.get("url"),
        response.get("data", {}).get("publicUrl")
        if isinstance(response.get("data"), dict)
        else None,
    ]
    for candidate in candidates:
        if not candidate:
            continue
        if candidate.startswith("//"):
            return f"https:{candidate}"
        if candidate.startswith("https://"):
            return candidate
    raise DatawrapperError(f"Datawrapper did not return a public URL for chart {chart_id}")


def publish(
    site: Path = Path("site"),
    config_path: Path = Path("configs/datawrapper_poc.toml"),
    env_path: Path = Path(".env"),
    client: DatawrapperClient | None = None,
) -> dict:
    client = client or DatawrapperClient(load_api_key(env_path))
    forecast = latest_forecast(site)
    chart_id = load_chart_id(config_path)
    action = "updated"
    if not chart_id:
        created = client.create_chart("Who will win the Premier League?")
        chart_id = created.get("id", "")
        save_chart_id(config_path, chart_id)
        action = "created"
    client.update_chart(chart_id, chart_properties(forecast))
    client.upload_data(chart_id, chart_data(forecast))
    published = client.publish_chart(chart_id)
    return {
        "action": action,
        "chart_id": chart_id,
        "url": public_url(published, chart_id),
        "snapshot_id": forecast["snapshot_id"],
    }
