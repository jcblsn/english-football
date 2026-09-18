"""Kalshi exchange price collection for English football trade research.

Only the public `/markets` list of the Predictions API is read, once a day
for each reviewed series. No order placement, portfolio access, WebSocket use
or high-frequency polling is in this module. Each collected page is retained
as an immutable raw response, and the market records it holds are normalized
into the canonical `kalshi_markets` table.

Kalshi-native identity is authoritative: every retained market keeps its
series, event and market tickers, its provider title and labels, and its
market timing. Repository identity (`competition_id`, `season_id`, `team_id`,
`match_id`, `side`) is a mapping, filled only where the provider evidence
names it. A null repository field is an unmapped market, not a missing
market, and the reason it is null is in the collection audit.
"""

import gzip
import json
import re
import time
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from epl_forecast.data.api_football import team_registry
from epl_forecast.data.capture import Fetcher, SourceAccessError
from epl_forecast.data.sources import season_name
from epl_forecast.datasets import Dataset, publish, timestamp
from epl_forecast.schema import fixture_id
from epl_forecast.snapshots import KALSHI_SERIES, SnapshotIndex, snapshot, snapshot_rows

BASE = "https://external-api.kalshi.com/trade-api/v2"
ZERO, ONE = Decimal(0), Decimal(1)
# The repository competition mapped from a reviewed Kalshi series. Every other
# collected series keeps Kalshi-native identity only.
EPL_COMPETITION_ID = "eng-premier-league"

# Reviewed English football series: one `series_ticker` filter on `/markets`
# each, read about once per day. Every ticker is verified against the live
# `/series` list (tags=Soccer) and the live `/markets` responses, not
# inferred from a title. KXEPLTOP carries the Top 2, Top 4, Top 6 and Top
# Half events in one series; the dedicated KXEPLTOP2, KXEPLTOP4 and
# KXEPLTOP6 series exist but hold no open market, so the thresholds are
# collected once, through KXEPLTOP.
#
# Kalshi lists soccer series for many other leagues, and derivative English
# series for spreads, totals, corners, halves and player statistics. They
# stay out of collection: this repository holds no identity for the clubs of
# another league, no reviewed evidence of how another game series orders a
# fixture, and no use for a derivative contract in match-result and
# season-outcome research.
SERIES = (
    "KXPREMIERLEAGUE",
    "KXEPLTOP",
    "KXEPLRELEGATION",
    "KXEPLLAST",
    "KXEPLGAME",
    "KXEFLCHAMPIONSHIP",
    "KXEFLCHAMPIONSHIPGAME",
    "KXEFLL1GAME",
    "KXENGNLGAME",
    "KXEFLCUP",
    "KXEFLPROMO",
)
# Series with one binary contract for each fixture outcome side.
GAME_SERIES = frozenset({"KXEPLGAME", "KXEFLCHAMPIONSHIPGAME", "KXEFLL1GAME", "KXENGNLGAME"})
# Series whose contracts carry repository Premier League identity.
EPL_SERIES = frozenset({"KXPREMIERLEAGUE", "KXEPLTOP", "KXEPLRELEGATION", "KXEPLGAME"})
# The one series whose event tickers have a reviewed home-away code order.
ORDERED_SERIES = "KXEPLGAME"
# Minimum gap between Kalshi requests.
REQUEST_GAP_SECONDS = 1.0
PAGE_LIMIT = 1000
MAX_PAGES = 25

# Kalshi-native market families. A season family keeps the provider
# threshold (Top 2, Top 4, Top 6, Top Half) as its detail instead of
# discarding contracts outside an initial scope.
MATCH_RESULT = "match_result"
CHAMPION = "champion"
TOP_FINISH = "top_finish"
RELEGATION = "relegation"
LAST_PLACE = "last_place"
PROMOTION = "promotion"
CUP_WINNER = "cup_winner"
# The reviewed family of each season series. A series that is not in this
# table and not a game series is unclassified, and its markets are audited
# instead of normalized into a guessed family.
SEASON_FAMILIES = {
    "KXPREMIERLEAGUE": CHAMPION,
    "KXEFLCHAMPIONSHIP": CHAMPION,
    "KXEPLTOP": TOP_FINISH,
    "KXEPLRELEGATION": RELEGATION,
    "KXEPLLAST": LAST_PLACE,
    "KXEFLPROMO": PROMOTION,
    "KXEFLCUP": CUP_WINNER,
}
# Repository families for the mapped English competitions. Kalshi-native
# families stay on every row so research can read both.
EPL_MATCH_RESULT = "epl_match_result"
EPL_CHAMPION = "epl_champion"
EPL_TOP_4 = "epl_top_4"
EPL_RELEGATION = "epl_relegation"

# Canonical column to provider field, grouped by the kind of value each
# holds: a price is dollars for one binary contract, so it reads as the
# implied probability; a count is contracts; liquidity is dollars of resting
# orders. Adding a retained field is one line here.
PRICE_FIELDS = {
    "yes_bid": "yes_bid_dollars",
    "yes_ask": "yes_ask_dollars",
    "no_bid": "no_bid_dollars",
    "no_ask": "no_ask_dollars",
    "last_price": "last_price_dollars",
    "previous_yes_bid": "previous_yes_bid_dollars",
    "previous_yes_ask": "previous_yes_ask_dollars",
    "previous_price": "previous_price_dollars",
}
MONEY_FIELDS = {"liquidity": "liquidity_dollars"}
COUNT_FIELDS = {
    "yes_bid_size": "yes_bid_size_fp",
    "yes_ask_size": "yes_ask_size_fp",
    "volume": "volume_fp",
    "volume_24h": "volume_24h_fp",
    "open_interest": "open_interest_fp",
}
TIME_FIELDS = {
    "open_time": "open_time",
    "close_time": "close_time",
    "created_time": "created_time",
    "updated_time": "updated_time",
    "occurrence_datetime": "occurrence_datetime",
    "latest_expiration_time": "latest_expiration_time",
}

# Match suffix codes reviewed against the live EPL game markets. The suffix
# is a short code, not necessarily the first letters: CFC is Chelsea, LFC is
# Liverpool. The yes-side label is the reviewed name and is kept as evidence
# next to each code. The other game series have no reviewed code list, so
# their contracts carry a club label without a home-away side.
EPL_TEAM_CODES = {
    "ARS": "arsenal",
    "AVL": "aston-villa",
    "BHA": "brighton-hove-albion",
    "BOU": "bournemouth",
    "BRE": "brentford",
    "BRI": "brighton-hove-albion",
    "BUR": "burnley",
    "CFC": "chelsea",
    "CHE": "chelsea",
    "COV": "coventry-city",
    "CRY": "crystal-palace",
    "EVE": "everton",
    "FUL": "fulham",
    "HUL": "hull-city",
    "IPS": "ipswich-town",
    "LEE": "leeds-united",
    "LEI": "leicester-city",
    "LFC": "liverpool",
    "MCI": "manchester-city",
    "MUN": "manchester-united",
    "NEW": "newcastle-united",
    "NFO": "nottingham-forest",
    "SUN": "sunderland",
    "TOT": "tottenham-hotspur",
    "WHU": "west-ham-united",
}

_KNOWN_TEAMS = None


def known_teams():
    global _KNOWN_TEAMS
    if _KNOWN_TEAMS is None:
        names = {}
        for name, team_id in team_registry().items():
            key = name.strip().lower()
            if key and key not in names:
                names[key] = team_id
        _KNOWN_TEAMS = names
    return _KNOWN_TEAMS


def resolve_team(name):
    """The repository team id of a Kalshi label, or None when it is not a club."""
    if name is None:
        return None, "missing: Kalshi response has no team label"
    if name.strip().lower() == "tie":
        return None, None
    found = known_teams().get(name.strip().lower())
    if found is not None:
        return found, None
    return None, f"unknown: {name!r} is not a reviewed team name; extend teams.csv"


def resolve_team_code(code, name):
    """The repository team id for a Kalshi match-market suffix, with the label as evidence.

    The suffix code is the primary key and the yes-side label corroborates it.
    A label that names another club, or no known club, leaves the market
    unresolved instead of trusting the code alone.
    """
    team, reason = resolve_team(name)
    mapped = EPL_TEAM_CODES.get(code.upper()) if code else None
    if mapped is not None:
        if team is not None:
            if mapped != team:
                return None, (
                    f"unknown: market suffix {code!r} maps to {mapped} "
                    f"but the label {name!r} resolves to {team}"
                )
            return mapped, None
        if name is None or not name.strip():
            return mapped, None
        return None, (
            f"unknown: market suffix {code!r} maps to {mapped} "
            f"but the label {name!r} is not that club"
        )
    if team is not None:
        return team, (
            f"unknown: market suffix {code!r} has no reviewed mapping, "
            "but the label resolves; extend EPL_TEAM_CODES"
        )
    return None, reason or f"unknown: market suffix {code!r} has no reviewed mapping"


def current_season(now=None):
    """The repository season a collection run is for. The season rolls over in July."""
    moment = now or datetime.now(UTC)
    return season_name(moment.year - (moment.month < 7))


def season_of(record, now=None):
    """The repository season a retained page was collected for."""
    return (record.get("context") or {}).get("season_id") or current_season(now)


def season_short(season_id):
    """The two-digit season code Kalshi uses in season event tickers.

    The code is the end year: the 2026-27 season is "27", as in
    KXPREMIERLEAGUE-27 and KXEPLTOP-27TOP4 on the live API.
    """
    return f"{(int(season_id[:4]) + 1) % 100:02d}"


def markets_url(series, status="open", limit=PAGE_LIMIT, cursor=None):
    """The one endpoint this module reads: one page of the markets of one series."""
    params = {"status": status, "limit": limit, "series_ticker": series}
    if cursor:
        params["cursor"] = cursor
    return f"{BASE}/markets?{urlencode(sorted(params.items()))}"


def decoded(payload):
    """The JSON body of a retained page, decompressing a gzip response."""
    return json.loads(gzip.decompress(payload) if payload[:2] == b"\x1f\x8b" else payload)


def request_page(fetcher, series, season_id, *, cursor=None):
    """Read one page of a series. Every page is a new request, paced by the collector.

    The `Fetcher` paces API-Football calls but not Kalshi calls, so this
    collector keeps its own minimum gap instead of bursting one request for
    each series and page.
    """
    time.sleep(REQUEST_GAP_SECONDS)
    record, payload = fetcher.get(
        "kalshi",
        markets_url(series, cursor=cursor),
        context={"endpoint": "markets", "series_ticker": series, "season_id": season_id},
    )
    record = {**record, "context": {**(record.get("context") or {}), "season_id": season_id}}
    try:
        return record, decoded(payload), payload
    except (ValueError, TypeError, OSError) as error:
        raise SourceAccessError(f"Kalshi market page is not JSON: {error}") from None


def _decimal(value, field, market_ticker, issues, resolution, minimum=None, maximum=None):
    """A Kalshi fixed-point value kept as its reported string, or None when missing.

    Prices use up to four decimals and quantities up to two; the canonical
    table keeps the exact reported string in DECIMAL columns instead of a
    binary float. Out-of-range or unparseable values stay null with an
    audited normalization issue.
    """
    if value is None or (isinstance(value, str) and value == ""):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        number = None
    if number is None or not number.is_finite():
        issues.append(
            {
                "table": "kalshi_markets",
                "market_ticker": market_ticker,
                "field": field,
                "reported_value": value,
                "resolution": f"unknown: Kalshi {resolution} is not numeric",
            }
        )
        return None
    if (minimum is not None and number < minimum) or (maximum is not None and number > maximum):
        issues.append(
            {
                "table": "kalshi_markets",
                "market_ticker": market_ticker,
                "field": field,
                "reported_value": value,
                "resolution": f"unknown: Kalshi {resolution} is out of range",
            }
        )
        return None
    return str(number)


def _decimals(market, fields, market_ticker, issues, resolution, minimum, maximum=None):
    """The canonical decimal columns of one market, read from their provider fields."""
    return {
        column: _decimal(
            market.get(source), column, market_ticker, issues, resolution, minimum, maximum
        )
        for column, source in fields.items()
    }


def _moment(value, field, market_ticker, issues):
    if value is None or value == "":
        return None
    try:
        return timestamp(value).isoformat()
    except (ValueError, TypeError):
        issues.append(
            {
                "table": "kalshi_markets",
                "market_ticker": market_ticker,
                "field": field,
                "reported_value": value,
                "resolution": "unknown: Kalshi timestamp is not RFC 3339",
            }
        )
        return None


def series_of(market, queried):
    """The series of a market record, which the /markets list does not repeat per row."""
    return market.get("series_ticker") or queried


_TOP_SUFFIX = re.compile(r"TOP\s*(\d+|HALF)\s*$", re.IGNORECASE)


def _top_threshold(event_ticker):
    """The Top-N threshold of a top-finish event, or None when it names none.

    KXEPLTOP carries Top 2, Top 4, Top 6 and Top Half events in one series
    (KXEPLTOP-27TOP4, KXEPLTOP-27TOPHALF). The provider threshold is kept
    verbatim as the family detail instead of discarding contracts outside an
    initial scope.
    """
    suffix = (event_ticker or "").rsplit("-", 1)[-1] if "-" in (event_ticker or "") else ""
    match = _TOP_SUFFIX.search(suffix.replace("_", " "))
    if not match:
        return None
    return "TOP_HALF" if match.group(1).upper() == "HALF" else f"TOP_{match.group(1)}"


def market_family(market, queried=None):
    """The Kalshi-native family of a market record, or None when unclassified.

    The reviewed series names the family: a game series is one fixture
    result, and every other series is the season outcome that
    `SEASON_FAMILIES` records. An unclassified series stays None, so the
    caller audits it instead of normalizing it into a guessed family.
    """
    series = series_of(market, queried)
    if series in GAME_SERIES:
        return MATCH_RESULT
    return SEASON_FAMILIES.get(series)


def family_detail(market, family, queried=None):
    """The provider threshold or event identity behind a season family."""
    if family == TOP_FINISH:
        return _top_threshold(market.get("event_ticker")) or (
            market.get("event_ticker") or series_of(market, queried)
        )
    if family == MATCH_RESULT:
        return None
    return market.get("event_ticker") or series_of(market, queried)


def epl_family(family, detail, series):
    """The repository family for a mapped English market, or None when unmapped."""
    if series == "KXEPLGAME" and family == MATCH_RESULT:
        return EPL_MATCH_RESULT
    if series == "KXPREMIERLEAGUE" and family == CHAMPION:
        return EPL_CHAMPION
    if series == "KXEPLTOP" and detail == "TOP_4":
        return EPL_TOP_4
    if series == "KXEPLRELEGATION" and family == RELEGATION:
        return EPL_RELEGATION
    return None


def event_participants(markets):
    """The yes-side labels grouped by event ticker within one retained page.

    Grouping evidence comes from one response, not from ticker syntax. A
    three-contract event (two clubs plus Tie) is one fixture; the labels name
    the participants.
    """
    grouped = {}
    for market in markets:
        if not isinstance(market, dict):
            continue
        event = market.get("event_ticker")
        if event:
            grouped.setdefault(event, set()).add((market.get("yes_sub_title") or "").strip())
    return grouped


def event_clubs(labels):
    """The two repository clubs the grouped yes-side labels of one event name, or None.

    The label set says which two clubs an event is about. It carries no
    home-away order, so it corroborates a fixture instead of ordering one.
    """
    names = [label for label in labels if label.lower() != "tie"]
    if len(names) != 2:
        return None
    clubs = {resolve_team(name)[0] for name in names}
    if None in clubs or len(clubs) != 2:
        return None
    return clubs


def fixture_from_codes(event_ticker):
    """The (home, away) team ids of the reviewed EPL event suffix codes, or None.

    An EPL game event ticker ends with two reviewed three-letter codes in
    home-away order: KXEPLGAME-26SEP20ARSCHE is Arsenal at home to Chelsea.
    """
    parts = (event_ticker or "").split("-")
    if len(parts) != 2 or parts[0] != ORDERED_SERIES or len(parts[1]) < 7:
        return None
    codes = parts[1][-6:]
    home = EPL_TEAM_CODES.get(codes[:3].upper())
    away = EPL_TEAM_CODES.get(codes[3:].upper())
    if home is None or away is None or home == away:
        return None
    return home, away


def fixture_teams(event_ticker, labels=None):
    """The (home, away) repository team ids named by a game event, or None.

    Home-away order comes only from the reviewed EPL suffix codes. The
    grouped labels of the same retained page corroborate them: an event
    whose labels name another pair of clubs stays unresolved. No other game
    series has reviewed ordering evidence, so alphabetical or ticker order
    never stands in for it and its events keep no side.
    """
    ordered = fixture_from_codes(event_ticker)
    if ordered is None:
        return None
    clubs = event_clubs(labels) if labels else None
    if clubs is not None and clubs != set(ordered):
        # The reviewed suffix codes contradict the grouped labels; trust
        # neither ordering for this event.
        return None
    return ordered


_SEASON_EVENT = re.compile(r"^[A-Z0-9]+-(\d{2})(?!\d)")


def event_season_code(event_ticker):
    """The two-digit season code a season event ticker names, or None."""
    found = _SEASON_EVENT.match(event_ticker or "")
    return found.group(1) if found else None


def market_identity(market, series, family, detail, season_id, participants, fixtures):
    """The repository identity of one market, and the reasons a field stays null.

    Kalshi-native identity is authoritative and always kept. A repository
    field is filled only where the provider evidence names it. The series
    names the competition. A season event ticker names the season. The
    reviewed EPL suffix codes order a fixture, corroborated by the labels
    grouped in the same event. The captured schedule confirms a match. Any
    field the evidence leaves open stays null with an audited reason, so no
    contract is filed under a season or a side that was assumed.
    """
    event = market.get("event_ticker")
    label = (market.get("yes_sub_title") or "").strip()
    repository_family = epl_family(family, detail, series) if series in EPL_SERIES else None
    competition_id = EPL_COMPETITION_ID if repository_family else None
    mapped_season, season_reason = None, None
    team, team_reason = None, None
    match_id, side = None, None
    if family != MATCH_RESULT:
        team, team_reason = resolve_team(market.get("yes_sub_title"))
        if repository_family is not None:
            if event_season_code(event) == season_short(season_id):
                mapped_season = season_id
            else:
                season_reason = (
                    f"unknown: event {event!r} does not name repository season {season_id}"
                )
    else:
        draw = label.lower() == "tie"
        if draw:
            side = "draw"
        elif series == ORDERED_SERIES:
            suffix = market["ticker"].rsplit("-", 1)[-1] if "-" in market["ticker"] else None
            team, team_reason = resolve_team_code(suffix, label)
        else:
            # The other game series have no reviewed code list, so identity
            # comes from the reviewed label alone.
            team, team_reason = resolve_team(market.get("yes_sub_title"))
        fixture = fixture_teams(event, participants.get(event) or None)
        if fixture is None:
            # Only the reviewed series is expected to name an ordered
            # fixture. Elsewhere an unordered event is not an anomaly.
            if series == ORDERED_SERIES and team_reason is None:
                team_reason = f"unknown: {event!r} names no reviewed fixture"
        elif draw or team in fixture:
            side = side or ("home" if team == fixture[0] else "away")
            if competition_id is not None:
                candidate = fixture_id(competition_id, season_id, *fixture)
                if candidate in fixtures:
                    match_id, mapped_season = candidate, season_id
                else:
                    season_reason = f"unknown: no captured schedule for {candidate} at retrieval"
        elif team_reason is None:
            team_reason = f"unknown: {label!r} plays in neither side of {event!r}"
    return (
        {
            "competition_id": competition_id,
            "season_id": mapped_season,
            "epl_family": repository_family,
            "team_id": team,
            "match_id": match_id,
            "side": side,
        },
        [reason for reason in (team_reason, season_reason) if reason is not None],
    )


def captured_fixtures(root, store, cutoff=None):
    """The match ids of the captured schedule that a market can link to.

    Reading the canonical schedule from R2 is the expensive part of
    normalizing a page, and a collection run adds no fixture while it reads
    the exchange. One run therefore reads the schedule once and normalizes
    every page against it. A replay reads it at the retrieval time of each
    page instead, which is the same evidence the capturing run had.

    Only the fixture table is registered. Kalshi identity needs no other
    canonical table, and registering one costs a request for each of its
    Parquet files.
    """
    data = Dataset(cutoff, workspace=root, store=store, tables=("fixtures",))
    try:
        return {row["match_id"] for row in data.rows("SELECT match_id FROM fixtures")}
    finally:
        data.close()


def normalize_page(record, body, root, season_id, store, issues, fixtures=None):
    if not isinstance(body, dict) or not isinstance(body.get("markets"), list):
        raise ValueError("Kalshi market page lacks a markets list")
    queried = (record.get("context") or {}).get("series_ticker")
    if fixtures is None:
        fixtures = captured_fixtures(root, store, timestamp(record["retrieved_at"]))
    participants = event_participants(body["markets"])
    rows = []
    for market in body["markets"]:
        if not isinstance(market, dict) or not market.get("ticker"):
            issues.append(
                {
                    "table": "kalshi_markets",
                    "market_ticker": (market or {}).get("ticker"),
                    "resolution": "unknown: Kalshi market record has no ticker",
                }
            )
            continue
        ticker = market["ticker"]
        series = series_of(market, queried)
        family = market_family(market, queried)
        if family is None:
            issues.append(
                {
                    "table": "kalshi_markets",
                    "market_ticker": ticker,
                    "reported_values": {
                        "series_ticker": series,
                        "event_ticker": market.get("event_ticker"),
                    },
                    "resolution": "unknown: Kalshi series is not a reviewed football series",
                }
            )
            continue
        detail = family_detail(market, family, queried)
        identity, reasons = market_identity(
            market, series, family, detail, season_id, participants, fixtures
        )
        for reason in reasons:
            issues.append(
                {
                    "table": "kalshi_markets",
                    "market_ticker": ticker,
                    "reported_values": {
                        "yes_sub_title": market.get("yes_sub_title"),
                        "event_ticker": market.get("event_ticker"),
                    },
                    "resolution": reason,
                }
            )
        rows.append(
            {
                "market_ticker": ticker,
                "event_ticker": market.get("event_ticker"),
                "series_ticker": series,
                "family": family,
                "family_detail": detail,
                **identity,
                "title": market.get("title"),
                "market_type": market.get("market_type"),
                "status": market.get("status"),
                "result": market.get("result") or None,
                "yes_label": market.get("yes_sub_title"),
                "no_label": market.get("no_sub_title"),
                **_decimals(market, PRICE_FIELDS, ticker, issues, "price", ZERO, ONE),
                **_decimals(market, MONEY_FIELDS, ticker, issues, "liquidity", ZERO),
                **_decimals(market, COUNT_FIELDS, ticker, issues, "contract count", ZERO),
                "can_close_early": (
                    None
                    if market.get("can_close_early") is None
                    else bool(market.get("can_close_early"))
                ),
                "price_ranges": (
                    None
                    if market.get("price_ranges") is None
                    else json.dumps(market.get("price_ranges"), sort_keys=True)
                ),
                **{
                    column: _moment(market.get(source), column, ticker, issues)
                    for column, source in TIME_FIELDS.items()
                },
            }
        )
    return rows


def ingest(root, record, payload, season_id=None, now=None, store=None, run=None, fixtures=None):
    """Normalize one retained Kalshi market page into the canonical table.

    With a `SeriesRun`, the page is also accounted to its series capture, so
    the run publishes the completion snapshot when its last page arrives.
    """
    body = decoded(payload)
    season = season_id or season_of(record, now)
    issues = []
    rows = normalize_page(record, body, root, season, store, issues, fixtures)
    if issues:
        record = {**record, "normalization_issues": issues}
    manifest = publish(root, record, {"kalshi_markets": rows})
    if run is not None:
        cursor = body.get("cursor") if isinstance(body, dict) else None
        run.page(root, record, cursor, manifest["rows"].get("kalshi_markets", 0))
    return manifest


def publish_series_snapshot(root, record, season_id, observed):
    """Record that one series query succeeded, with its total observed market count."""
    series = record["context"]["series_ticker"]
    return publish(
        root,
        record,
        {
            "source_snapshots": [
                snapshot(
                    KALSHI_SERIES,
                    series,
                    endpoint="markets",
                    row_count=observed,
                    competition_id=EPL_COMPETITION_ID if series in EPL_SERIES else None,
                    season_id=season_id if series in EPL_SERIES else None,
                )
            ]
        },
    )


class SeriesRun:
    """The pages of one series capture, which publish one completion snapshot.

    A series is one query scope spread over cursor pages, so the snapshot
    that records its retrieval belongs to the whole run and not to a page.
    Production paginates the run itself, and replay reads the retained pages
    of that same run in retrieval order. Both account their pages here, so a
    replayed history holds the snapshots the capturing run wrote. A run that
    never reaches the final empty cursor publishes nothing, and the series
    stays due.
    """

    def __init__(self):
        self.pending = {}

    def page(self, root, record, cursor, markets):
        """Account one normalized page, and publish the snapshot when the run ends."""
        series = (record.get("context") or {}).get("series_ticker")
        if not series:
            return None
        run = self.pending.get(series)
        if record["url"] == markets_url(series):
            run = self.pending[series] = {"markets": 0, "cursor": None}
        elif run is None or record["url"] != markets_url(series, cursor=run["cursor"]):
            # This page continues no run in progress, so the run it belongs
            # to is incomplete here and records no successful retrieval.
            self.pending.pop(series, None)
            return None
        run["markets"] += markets
        run["cursor"] = cursor or None
        if run["cursor"]:
            return None
        del self.pending[series]
        return publish_series_snapshot(root, record, season_of(record), run["markets"])


def series_snapshots(root, store):
    """The latest completed capture of each series, from the canonical history.

    Only the snapshot table is registered, and one run reads it once. It is
    the daily gate of every series, so reading it for each series in turn
    would repeat the same request against R2 eleven times.
    """
    data = Dataset(store=store, workspace=root, tables=("source_snapshots",))
    try:
        return SnapshotIndex(snapshot_rows(data))
    finally:
        data.close()


def is_fresh(snapshots, series, max_age, now=None):
    """True when a completed capture of this series is in the history and fresh."""
    row = snapshots.snapshot(KALSHI_SERIES, series)
    if row is None:
        return False
    age = ((now or datetime.now(UTC)) - timestamp(row["retrieved_at"])).total_seconds()
    return age < max_age if max_age is not None else True


def collect_series(fetcher, root, series, season_id, errors, store=None, fixtures=None):
    """Collect every page of one Kalshi series into the workspace.

    The series is collected from a new first page. A retained first page
    carries a cursor from its own retrieval, so reusing it would join pages
    of different observation times into one capture, or continue a cursor
    the exchange has already dropped.

    A run that reaches the final empty cursor publishes the completion
    snapshot of the series. A run that stops earlier publishes none, so the
    series stays due and the next run collects it whole.
    """
    run = SeriesRun()
    markets, pages, cursor = 0, 0, None
    while pages < MAX_PAGES:
        pages += 1
        try:
            record, body, payload = request_page(fetcher, series, season_id, cursor=cursor)
            manifest = ingest(
                root, record, payload, season_id, store=store, run=run, fixtures=fixtures
            )
            markets += manifest["rows"].get("kalshi_markets", 0)
            cursor = body.get("cursor") if isinstance(body, dict) else None
        except (ValueError, SourceAccessError, OSError) as error:
            errors.append(str(error))
            return {"markets": markets, "pages": pages}
        if not cursor:
            return {"markets": markets, "pages": pages}
    errors.append(f"Kalshi pagination did not finish for {series}")
    return {"markets": markets, "pages": pages}


def collect(root, season=None, store=None, fetcher=None, max_age=86400):
    """Collect open Kalshi football markets about once per day into a capture workspace.

    The completion snapshot of a series is written only after every page of
    a capture normalized, so a snapshot inside the refresh interval means
    the series is already in the canonical history. The run then skips it
    without a request, and without reading a retained raw file that the
    empty workspace of a production run does not hold.

    A failed daily attempt leaves its error in the report and no snapshot,
    so a later production run collects that series again.
    """
    now = datetime.now(UTC)
    season_id = season_name(season) if season is not None else current_season(now)
    fetcher = fetcher if fetcher is not None else Fetcher(root, store=store)
    errors = []
    observed = 0
    collected = []
    snapshots = series_snapshots(root, store)
    fixtures = captured_fixtures(root, store)
    for series in SERIES:
        if is_fresh(snapshots, series, max_age, now):
            continue
        result = collect_series(fetcher, root, series, season_id, errors, store, fixtures)
        observed += result["markets"]
        collected.append(series)
    return {
        "completed_at": now.isoformat(),
        "status": "partial" if errors else "complete",
        "errors": errors,
        "observed_markets": observed,
        "series": collected,
        "season_id": season_id,
        "reused": not collected,
    }
