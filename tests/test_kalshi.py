import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from epl_forecast.data import kalshi
from epl_forecast.data.capture import Fetcher
from epl_forecast.datasets import Dataset, publish

SEASON = "2026-2027"


@pytest.fixture(autouse=True)
def without_request_pacing(monkeypatch):
    monkeypatch.setattr(kalshi, "REQUEST_GAP_SECONDS", 0)


def scheduled_fixture(home="arsenal", away="chelsea"):
    return {
        "match_id": f"eng-premier-league:{SEASON}:{home}:{away}",
        "competition_id": "eng-premier-league",
        "season_id": SEASON,
        "stage": "regular",
        "home_team_id": home,
        "away_team_id": away,
        "match_date": "2026-09-20",
        "kickoff_time": "2026-09-20T14:00:00+00:00",
        "status": "scheduled",
    }


def workspace_with_fixture(tmp_path):
    publish(
        tmp_path,
        {
            "provider": "api_football",
            "retrieved_at": "2026-09-18T10:00:00+00:00",
            "evidence_basis": "captured",
            "source_sha256": "a" * 64,
            "context": {},
        },
        {"fixtures": [scheduled_fixture()]},
    )
    return tmp_path


def test_market_page_without_per_row_series_uses_the_queried_series(tmp_path):
    root = workspace_with_fixture(tmp_path)
    body = {"markets": [dict(market(), series_ticker=None)], "cursor": ""}
    manifest = kalshi.ingest(root, record(), json.dumps(body).encode())
    assert manifest["rows"] == {"kalshi_markets": 1}
    assert "normalization_issues" not in manifest["request"]
    data = Dataset(workspace=root)
    try:
        (row,) = data.rows(
            "SELECT series_ticker, family, family_detail, epl_family, competition_id, "
            "season_id FROM kalshi_markets"
        )
    finally:
        data.close()
    assert (row["series_ticker"], row["family"]) == ("KXPREMIERLEAGUE", "champion")
    assert row["family_detail"] == "KXPREMIERLEAGUE-27"
    assert row["epl_family"] == "epl_champion"
    assert row["competition_id"] == "eng-premier-league"
    assert row["season_id"] == SEASON


def record(series="KXPREMIERLEAGUE", retrieved_at="2026-09-18T12:00:00+00:00"):
    return {
        "provider": "kalshi",
        "retrieved_at": retrieved_at,
        "evidence_basis": "captured",
        "source_sha256": "b" * 64,
        "context": {"endpoint": "markets", "series_ticker": series, "season_id": SEASON},
    }


def market(**overrides):
    row = {
        "ticker": "KXPREMIERLEAGUE-27-ARS",
        "event_ticker": "KXPREMIERLEAGUE-27",
        "series_ticker": "KXPREMIERLEAGUE",
        "market_type": "binary",
        "status": "active",
        "result": "",
        "yes_sub_title": "Arsenal",
        "no_sub_title": "Arsenal",
        "title": "Will Arsenal win the English Premier League?",
        "yes_bid_dollars": "0.2400",
        "yes_ask_dollars": "0.2500",
        "no_bid_dollars": "0.7500",
        "no_ask_dollars": "0.7600",
        "last_price_dollars": "0.2450",
        "previous_yes_bid_dollars": "0.2300",
        "previous_yes_ask_dollars": "0.2400",
        "previous_price_dollars": "0.2350",
        "liquidity_dollars": "12.5000",
        "yes_bid_size_fp": "120.50",
        "yes_ask_size_fp": "80.00",
        "volume_fp": "1500.25",
        "volume_24h_fp": "100.00",
        "open_interest_fp": "900.00",
        "can_close_early": True,
        "price_ranges": [{"end": "1.0000", "start": "0.0000", "step": "0.0100"}],
        "open_time": "2026-07-01T12:00:00Z",
        "close_time": "2027-06-13T21:00:00Z",
        "created_time": "2026-07-01T10:00:00Z",
        "updated_time": "2026-09-18T11:00:00Z",
        "occurrence_datetime": "2027-06-07T21:00:00Z",
        "latest_expiration_time": "2027-06-13T21:00:00Z",
    }
    row.update(overrides)
    return row


def game_market(**overrides):
    row = market(
        ticker="KXEPLGAME-26SEP20ARSCHE-ARS",
        event_ticker="KXEPLGAME-26SEP20ARSCHE",
        series_ticker="KXEPLGAME",
        yes_sub_title="Arsenal",
        no_sub_title="Arsenal",
    )
    row.update(overrides)
    return row


def test_champion_market_resolves_team_and_keeps_fixed_point_values(tmp_path):
    root = workspace_with_fixture(tmp_path)
    manifest = kalshi.ingest(root, record(), json.dumps({"markets": [market()]}).encode())
    assert manifest["rows"] == {"kalshi_markets": 1}
    assert "normalization_issues" not in manifest["request"]
    data = Dataset(workspace=root)
    try:
        (row,) = data.rows("SELECT * FROM kalshi_markets")
    finally:
        data.close()
    assert (row["family"], row["team_id"], row["match_id"], row["side"]) == (
        "champion",
        "arsenal",
        None,
        None,
    )
    assert row["epl_family"] == "epl_champion"
    assert (row["competition_id"], row["season_id"]) == ("eng-premier-league", SEASON)
    assert (row["yes_bid"], row["yes_ask"], row["last_price"]) == (
        Decimal("0.24"),
        Decimal("0.25"),
        Decimal("0.245"),
    )
    assert (row["yes_bid_size"], row["volume"], row["open_interest"]) == (
        Decimal("120.5"),
        Decimal("1500.25"),
        Decimal("900"),
    )
    assert row["liquidity"] == Decimal("12.5")
    assert row["can_close_early"] is True
    assert json.loads(row["price_ranges"]) == [
        {"end": "1.0000", "start": "0.0000", "step": "0.0100"}
    ]
    assert row["title"] == "Will Arsenal win the English Premier League?"
    assert row["close_time"].isoformat() == "2027-06-13T21:00:00+00:00"


def test_sub_cent_and_fractional_values_are_kept(tmp_path):
    root = workspace_with_fixture(tmp_path)
    kalshi.ingest(
        root,
        record(),
        json.dumps(
            {
                "markets": [
                    market(
                        yes_bid_dollars="0.0025",
                        yes_ask_dollars="0.0035",
                        yes_bid_size_fp="2.50",
                        volume_fp="0.01",
                    )
                ]
            }
        ).encode(),
    )
    data = Dataset(workspace=root)
    try:
        (row,) = data.rows("SELECT yes_bid, yes_ask, yes_bid_size, volume FROM kalshi_markets")
    finally:
        data.close()
    assert (row["yes_bid"], row["yes_ask"]) == (Decimal("0.0025"), Decimal("0.0035"))
    assert (row["yes_bid_size"], row["volume"]) == (Decimal("2.5"), Decimal("0.01"))


def test_missing_bid_and_ask_stay_missing_without_an_issue(tmp_path):
    root = workspace_with_fixture(tmp_path)
    manifest = kalshi.ingest(
        root,
        record(),
        json.dumps(
            {
                "markets": [
                    market(yes_bid_dollars="0.0000", yes_ask_dollars=None, last_price_dollars="")
                ]
            }
        ).encode(),
    )
    assert manifest["request"].get("normalization_issues", []) == []
    data = Dataset(workspace=root)
    try:
        (row,) = data.rows("SELECT yes_bid, yes_ask, last_price FROM kalshi_markets")
    finally:
        data.close()
    assert (row["yes_bid"], row["yes_ask"], row["last_price"]) == (
        Decimal("0"),
        None,
        None,
    )


def test_match_market_links_all_three_sides_to_one_fixture(tmp_path):
    root = workspace_with_fixture(tmp_path)
    body = {
        "markets": [
            game_market(),
            game_market(
                ticker="KXEPLGAME-26SEP20ARSCHE-CHE",
                yes_sub_title="Chelsea",
                no_sub_title="Chelsea",
            ),
            game_market(
                ticker="KXEPLGAME-26SEP20ARSCHE-TIE",
                yes_sub_title="Tie",
                no_sub_title="Tie",
            ),
        ]
    }
    kalshi.ingest(root, record("KXEPLGAME"), json.dumps(body).encode())
    data = Dataset(workspace=root)
    try:
        rows = data.rows(
            "SELECT market_ticker, team_id, match_id, side FROM kalshi_markets ORDER BY 1"
        )
    finally:
        data.close()
    assert rows == [
        {
            "market_ticker": "KXEPLGAME-26SEP20ARSCHE-ARS",
            "team_id": "arsenal",
            "match_id": f"eng-premier-league:{SEASON}:arsenal:chelsea",
            "side": "home",
        },
        {
            "market_ticker": "KXEPLGAME-26SEP20ARSCHE-CHE",
            "team_id": "chelsea",
            "match_id": f"eng-premier-league:{SEASON}:arsenal:chelsea",
            "side": "away",
        },
        {
            "market_ticker": "KXEPLGAME-26SEP20ARSCHE-TIE",
            "team_id": None,
            "match_id": f"eng-premier-league:{SEASON}:arsenal:chelsea",
            "side": "draw",
        },
    ]


def test_unknown_team_and_fixture_are_audited_not_invented(tmp_path):
    root = workspace_with_fixture(tmp_path)
    body = {
        "markets": [
            market(yes_sub_title="Springfield Atoms"),
            game_market(
                ticker="KXEPLGAME-26SEP20ARSCHE-XYZ",
                event_ticker="KXEPLGAME-26SEP20ARSXYZ",
                yes_sub_title="Springfield Atoms",
                no_sub_title="Springfield Atoms",
            ),
        ]
    }
    manifest = kalshi.ingest(root, record("KXEPLGAME"), json.dumps(body).encode())
    issues = manifest["request"]["normalization_issues"]
    assert len(issues) == 2
    assert all("unknown:" in issue["resolution"] for issue in issues)
    data = Dataset(workspace=root)
    try:
        rows = data.rows("SELECT market_ticker, team_id, match_id FROM kalshi_markets ORDER BY 1")
    finally:
        data.close()
    assert all(row["team_id"] is None and row["match_id"] is None for row in rows)


def test_conflicting_code_and_label_is_unresolved(tmp_path):
    root = workspace_with_fixture(tmp_path)
    manifest = kalshi.ingest(
        root,
        record("KXEPLGAME"),
        json.dumps({"markets": [game_market(yes_sub_title="Chelsea")]}).encode(),
    )
    (issue,) = manifest["request"]["normalization_issues"]
    assert "maps to arsenal" in issue["resolution"] and "resolves to chelsea" in issue["resolution"]
    data = Dataset(workspace=root)
    try:
        (row,) = data.rows("SELECT team_id, match_id FROM kalshi_markets")
    finally:
        data.close()
    assert (row["team_id"], row["match_id"]) == (None, None)


def test_top_thresholds_are_all_retained_with_provider_detail(tmp_path):
    root = workspace_with_fixture(tmp_path)
    body = {
        "markets": [
            market(
                ticker="KXEPLTOP-27TOP4-ARS",
                event_ticker="KXEPLTOP-27TOP4",
                series_ticker="KXEPLTOP",
            ),
            market(
                ticker="KXEPLTOP-27TOP2-ARS",
                event_ticker="KXEPLTOP-27TOP2",
                series_ticker="KXEPLTOP",
            ),
            market(
                ticker="KXEPLTOP-27TOP6-ARS",
                event_ticker="KXEPLTOP-27TOP6",
                series_ticker="KXEPLTOP",
            ),
            market(
                ticker="KXEPLTOP-27TOPHALF-ARS",
                event_ticker="KXEPLTOP-27TOPHALF",
                series_ticker="KXEPLTOP",
            ),
        ]
    }
    manifest = kalshi.ingest(root, record("KXEPLTOP"), json.dumps(body).encode())
    assert "normalization_issues" not in manifest["request"]
    data = Dataset(workspace=root)
    try:
        rows = data.rows(
            "SELECT market_ticker, family, family_detail, epl_family, team_id "
            "FROM kalshi_markets ORDER BY 1"
        )
    finally:
        data.close()
    assert rows == [
        {
            "market_ticker": "KXEPLTOP-27TOP2-ARS",
            "family": "top_finish",
            "family_detail": "TOP_2",
            "epl_family": None,
            "team_id": "arsenal",
        },
        {
            "market_ticker": "KXEPLTOP-27TOP4-ARS",
            "family": "top_finish",
            "family_detail": "TOP_4",
            "epl_family": "epl_top_4",
            "team_id": "arsenal",
        },
        {
            "market_ticker": "KXEPLTOP-27TOP6-ARS",
            "family": "top_finish",
            "family_detail": "TOP_6",
            "epl_family": None,
            "team_id": "arsenal",
        },
        {
            "market_ticker": "KXEPLTOP-27TOPHALF-ARS",
            "family": "top_finish",
            "family_detail": "TOP_HALF",
            "epl_family": None,
            "team_id": "arsenal",
        },
    ]


def test_other_english_series_keep_provider_identity_without_a_side(tmp_path):
    """Only the EPL game series has reviewed home-away codes, so no other event is ordered."""
    root = workspace_with_fixture(tmp_path)
    body = {
        "markets": [
            market(
                ticker="KXEFLCHAMPIONSHIP-27-NOR",
                event_ticker="KXEFLCHAMPIONSHIP-27",
                series_ticker="KXEFLCHAMPIONSHIP",
                yes_sub_title="Norwich",
                no_sub_title="Norwich",
                title="Will Norwich win the Championship?",
            ),
            market(
                ticker="KXEFLCHAMPIONSHIPGAME-26SEP20NORBOL-NOR",
                event_ticker="KXEFLCHAMPIONSHIPGAME-26SEP20NORBOL",
                series_ticker="KXEFLCHAMPIONSHIPGAME",
                yes_sub_title="Norwich",
                no_sub_title="Norwich",
                title="Norwich wins",
            ),
            market(
                ticker="KXEFLCHAMPIONSHIPGAME-26SEP20NORBOL-TIE",
                event_ticker="KXEFLCHAMPIONSHIPGAME-26SEP20NORBOL",
                series_ticker="KXEFLCHAMPIONSHIPGAME",
                yes_sub_title="Tie",
                no_sub_title="Tie",
                title="Tie is the result",
            ),
            market(
                ticker="KXEFLCHAMPIONSHIPGAME-26SEP20NORBOL-BOL",
                event_ticker="KXEFLCHAMPIONSHIPGAME-26SEP20NORBOL",
                series_ticker="KXEFLCHAMPIONSHIPGAME",
                yes_sub_title="Bolton",
                no_sub_title="Bolton",
                title="Bolton wins",
            ),
        ]
    }
    manifest = kalshi.ingest(root, record("KXEFLCHAMPIONSHIP"), json.dumps(body).encode())
    assert "normalization_issues" not in manifest["request"]
    data = Dataset(workspace=root)
    try:
        rows = data.rows(
            "SELECT market_ticker, family, competition_id, season_id, team_id, match_id, side "
            "FROM kalshi_markets ORDER BY 1"
        )
    finally:
        data.close()
    assert [(row["family"], row["team_id"], row["side"]) for row in rows] == [
        ("champion", "norwich-city", None),
        ("match_result", "bolton-wanderers", None),
        ("match_result", "norwich-city", None),
        ("match_result", None, "draw"),
    ]
    assert all(
        row["competition_id"] is None and row["season_id"] is None and row["match_id"] is None
        for row in rows
    )


def test_a_series_outside_the_reviewed_set_is_audited_not_normalized(tmp_path):
    root = workspace_with_fixture(tmp_path)
    manifest = kalshi.ingest(
        root,
        record("KXPREMIERLEAGUE"),
        json.dumps(
            {
                "markets": [
                    market(
                        ticker="KXLALIGA-27-RMA",
                        event_ticker="KXLALIGA-27",
                        series_ticker="KXLALIGA",
                        yes_sub_title="Real Madrid",
                        no_sub_title="Real Madrid",
                    )
                ]
            }
        ).encode(),
    )
    assert manifest["rows"] == {"kalshi_markets": 0}
    (issue,) = manifest["request"]["normalization_issues"]
    assert "not a reviewed football series" in issue["resolution"]


def test_a_contract_of_another_season_keeps_no_repository_season(tmp_path):
    """The wall clock never assigns the season: the event ticker has to name it."""
    root = workspace_with_fixture(tmp_path)
    manifest = kalshi.ingest(
        root,
        record(),
        json.dumps(
            {
                "markets": [
                    market(ticker="KXPREMIERLEAGUE-28-ARS", event_ticker="KXPREMIERLEAGUE-28")
                ]
            }
        ).encode(),
    )
    (issue,) = manifest["request"]["normalization_issues"]
    assert "does not name repository season 2026-2027" in issue["resolution"]
    data = Dataset(workspace=root)
    try:
        (row,) = data.rows(
            "SELECT competition_id, season_id, epl_family, team_id FROM kalshi_markets"
        )
    finally:
        data.close()
    assert row["season_id"] is None
    assert (row["competition_id"], row["epl_family"]) == ("eng-premier-league", "epl_champion")
    assert row["team_id"] == "arsenal"


def test_a_top_event_without_a_threshold_stays_top_finish(tmp_path):
    root = workspace_with_fixture(tmp_path)
    body = {
        "markets": [
            market(
                ticker="KXEPLTOP-27-ARS",
                event_ticker="KXEPLTOP-27",
                series_ticker="KXEPLTOP",
                title="Will Arsenal finish in the top of the Premier League season?",
            )
        ]
    }
    manifest = kalshi.ingest(root, record("KXEPLTOP"), json.dumps(body).encode())
    assert "normalization_issues" not in manifest["request"]
    data = Dataset(workspace=root)
    try:
        (row,) = data.rows(
            "SELECT family, family_detail, competition_id, epl_family FROM kalshi_markets"
        )
    finally:
        data.close()
    assert (row["family"], row["family_detail"]) == ("top_finish", "KXEPLTOP-27")
    assert (row["competition_id"], row["epl_family"]) == (None, None)


def test_relegation_and_invalid_prices(tmp_path):
    root = workspace_with_fixture(tmp_path)
    manifest = kalshi.ingest(
        root,
        record("KXEPLRELEGATION"),
        json.dumps(
            {
                "markets": [
                    market(
                        ticker="KXEPLRELEGATION-27-ARS",
                        event_ticker="KXEPLRELEGATION-27",
                        series_ticker="KXEPLRELEGATION",
                        yes_bid_dollars="1.2000",
                        volume_fp="many",
                    )
                ]
            }
        ).encode(),
    )
    data = Dataset(workspace=root)
    try:
        (row,) = data.rows(
            "SELECT family, epl_family, team_id, yes_bid, volume FROM kalshi_markets",
        )
    finally:
        data.close()
    assert (row["family"], row["team_id"]) == ("relegation", "arsenal")
    assert row["epl_family"] == "epl_relegation"
    assert (row["yes_bid"], row["volume"]) == (None, None)
    resolutions = [issue["resolution"] for issue in manifest["request"]["normalization_issues"]]
    assert any("out of range" in resolution for resolution in resolutions)
    assert any("not numeric" in resolution for resolution in resolutions)


def test_market_without_a_captured_schedule_stays_unlinked(tmp_path):
    root = tmp_path
    body = {
        "markets": [
            game_market(),
            game_market(
                ticker="KXEPLGAME-26SEP20ARSCHE-CHE",
                yes_sub_title="Chelsea",
                no_sub_title="Chelsea",
            ),
            game_market(
                ticker="KXEPLGAME-26SEP20ARSCHE-TIE",
                yes_sub_title="Tie",
                no_sub_title="Tie",
            ),
        ]
    }
    manifest = kalshi.ingest(root, record("KXEPLGAME"), json.dumps(body).encode())
    issues = manifest["request"]["normalization_issues"]
    assert any("no captured schedule" in issue["resolution"] for issue in issues)
    data = Dataset(workspace=root)
    try:
        rows = data.rows("SELECT team_id, match_id, side FROM kalshi_markets ORDER BY 1")
    finally:
        data.close()
    assert [(row["team_id"], row["match_id"]) for row in rows] == [
        ("arsenal", None),
        ("chelsea", None),
        (None, None),
    ]


class ScriptedFetcher(Fetcher):
    def __init__(self, root, pages):
        super().__init__(root)
        self.pages = pages

    def get(self, provider, url, *, context=None, max_age=None, historical=False):
        from epl_forecast.data.capture import SourceAccessError
        from epl_forecast.storage import json_bytes, sha256_bytes, write_immutable

        try:
            body = self.pages[url]
        except KeyError:
            raise SourceAccessError(f"Cannot retrieve {url}: simulated outage") from None
        payload = json.dumps(body).encode()
        digest = sha256_bytes(payload)
        path = self.root / "raw" / provider / f"{digest}.json"
        write_immutable(path, payload)
        record = {
            "provider": provider,
            "url": url,
            "retrieved_at": datetime.now(UTC).isoformat(),
            "evidence_basis": "captured",
            "source_sha256": digest,
            "raw_path": str(path.relative_to(self.root)),
            "context": context or {},
        }
        request_id = sha256_bytes(json_bytes(record))
        write_immutable(self.root / "requests" / f"{request_id}.json", json_bytes(record))
        self.captured.add((url, record["retrieved_at"]))
        return record, payload


class ManifestStore:
    """An R2 stand-in that serves the canonical batches of an earlier capture.

    Production collects into a new empty workspace each run, so a reused
    series must be decided from the canonical history alone. Downloading a
    retained raw file is a failure, not a fallback.
    """

    def __init__(self, root):
        self.manifests = [
            json.loads(path.read_text()) for path in sorted((root / "manifests").glob("*.json"))
        ]
        self.root = root

    def get_json(self, key, default=None):
        if key == "state/manifests.json":
            return {"schema_version": 1, "manifests": self.manifests}
        return default

    def uri(self, key):
        return str(self.root / key)

    def configure_duckdb(self, connection, name="page324_r2"):
        pass

    def download(self, key, destination):
        raise AssertionError(f"A reused Kalshi series must not read a retained raw: {key}")


def scripted_collection(tmp_path, bodies):
    root = workspace_with_fixture(tmp_path)
    pages = {}
    for series, body in bodies.items():
        pages[kalshi.markets_url(series)] = body
        cursor = body.get("cursor")
        while cursor:
            key = kalshi.markets_url(series, cursor=cursor)
            pages[key] = {"markets": [], "cursor": ""}
            cursor = None
    for series in kalshi.SERIES:
        pages.setdefault(kalshi.markets_url(series), {"markets": [], "cursor": ""})
    fetcher = ScriptedFetcher(root, pages)
    return root, kalshi.collect(root, season=2026, fetcher=fetcher)


def test_pagination_collects_every_page(tmp_path):
    first = {"markets": [market()], "cursor": "next"}
    second = {"markets": [market(ticker="KXPREMIERLEAGUE-27-CHE", yes_sub_title="Chelsea")]}
    root = workspace_with_fixture(tmp_path)
    pages = {kalshi.markets_url("KXPREMIERLEAGUE"): first}
    for series in kalshi.SERIES:
        if series != "KXPREMIERLEAGUE":
            pages[kalshi.markets_url(series)] = {"markets": [], "cursor": ""}
    pages[kalshi.markets_url("KXPREMIERLEAGUE", cursor="next")] = second
    report = kalshi.collect(root, season=2026, fetcher=ScriptedFetcher(root, pages))
    assert report["status"] == "complete"
    assert report["observed_markets"] == 2
    data = Dataset(workspace=root)
    try:
        rows = data.rows("SELECT market_ticker FROM kalshi_markets ORDER BY 1")
    finally:
        data.close()
    assert [row["market_ticker"] for row in rows] == [
        "KXPREMIERLEAGUE-27-ARS",
        "KXPREMIERLEAGUE-27-CHE",
    ]


def test_partial_pagination_retries_the_unfinished_series(tmp_path):
    """A retained first page with a failed second page stays due, not reused."""
    root = workspace_with_fixture(tmp_path)
    first = {"markets": [market()], "cursor": "next"}
    pages = {kalshi.markets_url("KXPREMIERLEAGUE"): first}
    fetcher = ScriptedFetcher(root, pages)
    errors = []
    result = kalshi.collect_series(fetcher, root, "KXPREMIERLEAGUE", SEASON, errors)
    assert errors and result["markets"] == 1
    # The next run must not treat the retained first page as a completed
    # capture: the series has no snapshot, so it stays due and the second
    # page is retried.
    fetcher.pages[kalshi.markets_url("KXPREMIERLEAGUE", cursor="next")] = {
        "markets": [market(ticker="KXPREMIERLEAGUE-27-CHE", yes_sub_title="Chelsea")]
    }
    errors.clear()
    result = kalshi.collect_series(fetcher, root, "KXPREMIERLEAGUE", SEASON, errors)
    # Both pages are collected again, from a new first page.
    assert errors == [] and (result["markets"], result["pages"]) == (2, 2)
    data = Dataset(workspace=root)
    try:
        rows = data.rows("SELECT market_ticker FROM kalshi_markets ORDER BY 1")
    finally:
        data.close()
    assert [row["market_ticker"] for row in rows] == [
        "KXPREMIERLEAGUE-27-ARS",
        "KXPREMIERLEAGUE-27-CHE",
    ]


def test_a_completed_series_is_reused_in_a_fresh_production_workspace(tmp_path):
    """The later run of a day gets a new empty workspace, and still sends no request."""
    first_root, first = scripted_collection(
        tmp_path / "morning", {"KXPREMIERLEAGUE": {"markets": [market()]}}
    )
    assert first["observed_markets"] == 1
    store = ManifestStore(first_root)
    workspace = tmp_path / "afternoon"
    workspace.mkdir()
    fetcher = ScriptedFetcher(workspace, {})
    fetcher.store = store

    second = kalshi.collect(workspace, season=2026, store=store, fetcher=fetcher)

    assert second["errors"] == []
    assert (second["series"], second["observed_markets"], second["reused"]) == ([], 0, True)
    assert not (workspace / "manifests").exists()


def test_a_collection_run_reads_the_captured_schedule_once(tmp_path, monkeypatch):
    """Reading the canonical schedule from R2 is the costly part of normalizing a page."""
    root = workspace_with_fixture(tmp_path)
    pages = {
        kalshi.markets_url("KXPREMIERLEAGUE"): {"markets": [market()], "cursor": "next"},
        kalshi.markets_url("KXPREMIERLEAGUE", cursor="next"): {
            "markets": [market(ticker="KXPREMIERLEAGUE-27-CHE", yes_sub_title="Chelsea")]
        },
    }
    for series in kalshi.SERIES:
        pages.setdefault(kalshi.markets_url(series), {"markets": [], "cursor": ""})
    reads = []
    schedule = kalshi.captured_fixtures

    def counted(root, store, cutoff=None):
        reads.append(cutoff)
        return schedule(root, store, cutoff)

    monkeypatch.setattr(kalshi, "captured_fixtures", counted)
    report = kalshi.collect(root, season=2026, fetcher=ScriptedFetcher(root, pages))

    assert report["observed_markets"] == 2
    assert reads == [None]


def test_a_stale_snapshot_makes_the_series_due_again(tmp_path):
    root, first = scripted_collection(tmp_path, {"KXPREMIERLEAGUE": {"markets": [market()]}})
    assert first["reused"] is False
    pages = {kalshi.markets_url(series): {"markets": [], "cursor": ""} for series in kalshi.SERIES}
    pages[kalshi.markets_url("KXPREMIERLEAGUE")] = {"markets": [market()]}

    stale = kalshi.collect(root, season=2026, fetcher=ScriptedFetcher(root, pages), max_age=0)

    assert stale["errors"] == []
    assert set(stale["series"]) == set(kalshi.SERIES)


def test_retry_after_failure_collects_on_the_next_run(tmp_path):
    root = workspace_with_fixture(tmp_path)
    pages = {
        kalshi.markets_url("KXPREMIERLEAGUE"): {"markets": [market()]},
        kalshi.markets_url("KXEPLTOP"): {"markets": [], "cursor": ""},
    }
    fetcher = ScriptedFetcher(root, pages)
    broken = kalshi.markets_url("KXEPLTOP")
    del fetcher.pages[broken]
    errors = []
    result = kalshi.collect_series(fetcher, root, "KXEPLTOP", SEASON, errors)
    assert errors and result["markets"] == 0
    fetcher.pages[broken] = {"markets": [], "cursor": ""}
    errors.clear()
    result = kalshi.collect_series(fetcher, root, "KXEPLTOP", SEASON, errors)
    assert errors == [] and result["pages"] == 1


def test_multiple_observations_support_cutoff_reads_and_raw_linkage(tmp_path):
    from epl_forecast.data.collect import kalshi_audit

    root = workspace_with_fixture(tmp_path)
    first = {**record(retrieved_at="2026-09-18T12:00:00+00:00"), "source_sha256": "c" * 64}
    second = {**record(retrieved_at="2026-09-19T12:00:00+00:00"), "source_sha256": "d" * 64}
    kalshi.ingest(root, first, json.dumps({"markets": [market()]}).encode())
    kalshi.ingest(
        root, second, json.dumps({"markets": [market(last_price_dollars="0.3000")]}).encode()
    )
    current = Dataset(workspace=root)
    try:
        assert current.rows("SELECT count(*) AS n FROM kalshi_markets_observations") == [{"n": 2}]
        assert current.rows(
            "SELECT last_price FROM kalshi_markets_observations ORDER BY retrieved_at"
        ) == [
            {"last_price": Decimal("0.245")},
            {"last_price": Decimal("0.3")},
        ]
        manifests = [
            json.loads(path.read_text()) for path in sorted((root / "manifests").glob("*.json"))
        ]
        assert {"c" * 64, "d" * 64} <= {
            manifest["request"]["source_sha256"] for manifest in manifests
        }
        for manifest in manifests:
            for row in manifest["files"]:
                assert (root / row["path"]).exists()
    finally:
        current.close()
    historical = Dataset("2026-09-18T13:00:00+00:00", workspace=root)
    try:
        assert historical.rows("SELECT last_price FROM kalshi_markets_observations") == [
            {"last_price": Decimal("0.245")}
        ]
        report = kalshi_audit(historical)
    finally:
        historical.close()
    assert report["missing_series"] == sorted(set(kalshi.SERIES) - {"KXPREMIERLEAGUE"})
    assert report["observed_markets"]["KXPREMIERLEAGUE"]["markets"] == 1
    assert report["observed_markets"]["KXPREMIERLEAGUE"]["unresolved_team"] == 0


def test_collection_report_and_audit_show_due_state_and_unresolved(tmp_path):
    from epl_forecast.data.collect import kalshi_audit

    root, report = scripted_collection(tmp_path, {"KXPREMIERLEAGUE": {"markets": [market()]}})
    assert report["season_id"] == SEASON
    assert set(report["series"]) == set(kalshi.SERIES)
    assert report["observed_markets"] == 1
    data = Dataset(workspace=root)
    try:
        audit = kalshi_audit(data)
    finally:
        data.close()
    assert audit["due_series"] == []
    assert audit["observed_series"] == ["KXPREMIERLEAGUE"]
    assert set(audit["missing_series"]) == set(kalshi.SERIES) - {"KXPREMIERLEAGUE"}
    # A capture older than the refresh interval is due again, as it is for
    # collection: a snapshot from last week is not a collected series.
    later = datetime.now(UTC) + timedelta(days=7)
    data = Dataset(workspace=root)
    try:
        assert kalshi_audit(data, now=later)["due_series"] == sorted(kalshi.SERIES)
    finally:
        data.close()


def test_kalshi_audit_separates_failed_identity_from_expected_null_identity(tmp_path):
    """A draw names no club, and an unmapped competition has no repository fixture."""
    from epl_forecast.data.collect import kalshi_audit

    root = workspace_with_fixture(tmp_path)
    kalshi.ingest(
        root,
        record("KXEPLGAME"),
        json.dumps(
            {
                "markets": [
                    game_market(yes_sub_title="Springfield Atoms"),
                    game_market(
                        ticker="KXEPLGAME-26SEP20ARSCHE-TIE",
                        yes_sub_title="Tie",
                        no_sub_title="Tie",
                    ),
                ]
            }
        ).encode(),
    )
    kalshi.ingest(
        root,
        record("KXENGNLGAME"),
        json.dumps(
            {
                "markets": [
                    market(
                        ticker="KXENGNLGAME-26SEP20YORALT-YOR",
                        event_ticker="KXENGNLGAME-26SEP20YORALT",
                        series_ticker="KXENGNLGAME",
                        yes_sub_title="York City",
                        no_sub_title="York City",
                    )
                ]
            }
        ).encode(),
    )
    data = Dataset(workspace=root)
    try:
        audit = kalshi_audit(data)
    finally:
        data.close()
    epl = audit["observed_markets"]["KXEPLGAME"]
    # The unresolved label counts once. The draw contract names no club by
    # design and still links to the scheduled fixture, so it counts in
    # neither column.
    assert (epl["unresolved_team"], epl["unresolved_fixture"]) == (1, 1)
    national = audit["observed_markets"]["KXENGNLGAME"]
    assert (national["unresolved_team"], national["unresolved_fixture"]) == (0, 0)
    assert national["unmapped_fixture"] == 1


def test_kalshi_prices_do_not_change_the_forecast_fingerprint(tmp_path):
    from epl_forecast.pipeline import information_fingerprint

    root = workspace_with_fixture(tmp_path)
    before = Dataset(workspace=root)
    try:
        first = information_fingerprint(before, "eng-premier-league")
    finally:
        before.close()
    kalshi.ingest(root, record(), json.dumps({"markets": [market()]}).encode())
    after = Dataset(workspace=root)
    try:
        assert information_fingerprint(after, "eng-premier-league") == first
    finally:
        after.close()


def test_analysis_views_expose_history_and_unresolved_cases(tmp_path):
    from test_analysis import ObjectStore

    from epl_forecast.analysis import open_analysis_session

    root = workspace_with_fixture(tmp_path)
    first = {**record(retrieved_at="2026-09-18T12:00:00+00:00"), "source_sha256": "c" * 64}
    second = {**record(retrieved_at="2026-09-19T12:00:00+00:00"), "source_sha256": "d" * 64}
    kalshi.ingest(root, first, json.dumps({"markets": [market()]}).encode())
    kalshi.ingest(
        root, second, json.dumps({"markets": [market(yes_sub_title="Springfield Atoms")]}).encode()
    )
    manifests = [
        json.loads(path.read_text()) for path in sorted((root / "manifests").glob("*.json"))
    ]

    class Store(ObjectStore):
        def get_json(self, key, default=None):
            if key == "state/manifests.json":
                return {"schema_version": 1, "manifests": manifests}
            return default

        def uri(self, key):
            return str(root / key)

        def configure_duckdb(self, connection, name="page324_r2"):
            pass

    session = open_analysis_session(data_store=Store(), include_derived=False)
    try:
        assert session.rows("SELECT count(*) AS n FROM analysis.kalshi_markets") == [{"n": 2}]
        assert session.rows(
            "SELECT count(*) AS n FROM analysis.kalshi_markets WHERE epl_family='epl_champion'"
        ) == [{"n": 2}]
        unresolved = session.rows(
            "SELECT market_ticker FROM analysis.kalshi_markets WHERE team_id IS NULL"
        )
        assert [row["market_ticker"] for row in unresolved] == ["KXPREMIERLEAGUE-27-ARS"]
        assert session.rows("SELECT count(*) AS n FROM analysis.kalshi_snapshots") == [{"n": 0}]
        # The query skill is told to read meaning from the catalog, so a
        # price must state that it is dollars for one binary contract.
        catalog = dict(
            (row["column_name"], row["unit_or_scale"])
            for row in session.rows(
                "SELECT column_name, unit_or_scale FROM analysis.column_catalog "
                "WHERE object_name='kalshi_markets'"
            )
        )
        assert catalog["yes_bid"] == "dollars from 0 to 1, which is the implied probability"
        assert catalog["volume"] == "contracts"
        assert catalog["side"] == "home, draw, or away"
        historical = session.rows(
            "SELECT last_price FROM analysis.kalshi_markets "
            "WHERE retrieved_at <= TIMESTAMPTZ '2026-09-18T13:00:00+00:00'"
        )
        assert historical == [{"last_price": Decimal("0.245")}]
        linkage = session.rows(
            "SELECT market_ticker, retrieved_at, source_sha256 FROM analysis.kalshi_markets "
            "ORDER BY retrieved_at"
        )
        assert [row["source_sha256"] for row in linkage] == ["c" * 64, "d" * 64]
    finally:
        session.close()
