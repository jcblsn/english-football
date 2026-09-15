"""Canonical local datasets; no network or provider payload interpretation."""

import json
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb

from epl_forecast.schema import Fixture, Match
from epl_forecast.storage import (
    file_hash,
    json_bytes,
    r2_store_if_configured,
    sha256_bytes,
    write_immutable,
)

COMMON = (
    "provider VARCHAR, retrieved_at TIMESTAMPTZ, evidence_basis VARCHAR, source_sha256 VARCHAR, "
    "normalization_version INTEGER"
)
# Stored instants must read back in UTC, not in the time zone of the machine that runs the product.
SESSION_TIME_ZONE = "SET TimeZone='UTC'"
SCHEMAS = {
    "competition_seasons": "competition_id VARCHAR, season_id VARCHAR, team_ids VARCHAR[], "
    "expected_matches INTEGER, coverage VARCHAR",
    "teams": "team_id VARCHAR, name VARCHAR, api_id BIGINT",
    "fixtures": "match_id VARCHAR, competition_id VARCHAR, season_id VARCHAR, stage VARCHAR, "
    "home_team_id VARCHAR, away_team_id VARCHAR, match_date DATE, kickoff_time TIMESTAMPTZ, "
    "status VARCHAR, home_goals INTEGER, away_goals INTEGER, api_id BIGINT, source_row INTEGER, "
    "source_time VARCHAR",
    "players": "player_id VARCHAR, api_id BIGINT, name VARCHAR, birth_date DATE, "
    "understat_id VARCHAR, fpl_code VARCHAR",
    "memberships": "player_id VARCHAR, team_id VARCHAR, season_id VARCHAR, competition_id VARCHAR, "
    "position VARCHAR, basis VARCHAR, scope VARCHAR",
    "appearances": "match_id VARCHAR, player_id VARCHAR, team_id VARCHAR, competition_id VARCHAR, "
    "season_id VARCHAR, kickoff_time TIMESTAMPTZ, position VARCHAR, "
    "starts INTEGER, minutes INTEGER, "
    "goals INTEGER, assists INTEGER, shots INTEGER, shots_on_target INTEGER, saves INTEGER, "
    "yellow_cards INTEGER, red_cards INTEGER, rating DOUBLE, passes_total INTEGER, "
    "key_passes INTEGER, pass_accuracy VARCHAR, tackles INTEGER, interceptions INTEGER, "
    "duels_total INTEGER, duels_won INTEGER, dribbles_attempted INTEGER, "
    "dribbles_successful INTEGER, fouls_drawn INTEGER, fouls_committed INTEGER",
    "availability": "player_id VARCHAR, fpl_code VARCHAR, team_id VARCHAR, competition_id VARCHAR, "
    "season_id VARCHAR, match_id VARCHAR, scope VARCHAR, status VARCHAR, reason VARCHAR, "
    "start_date DATE, end_date DATE, chance_this_round INTEGER, chance_next_round INTEGER, "
    "current_round INTEGER, next_round INTEGER, news_added TIMESTAMPTZ",
    "transfers": "player_id VARCHAR, transfer_date DATE, from_team_id VARCHAR, to_team_id VARCHAR, "
    "transfer_type VARCHAR",
    "team_process": "match_id VARCHAR, team_id VARCHAR, competition_id VARCHAR, season_id VARCHAR, "
    "xg DOUBLE, shots INTEGER, shots_on_target INTEGER, source_match_id VARCHAR",
    "player_process": "match_id VARCHAR, team_id VARCHAR, player_id VARCHAR, understat_id VARCHAR, "
    "competition_id VARCHAR, season_id VARCHAR, position VARCHAR, minutes INTEGER, xg DOUBLE, "
    "xa DOUBLE, shots INTEGER",
    "odds": "match_id VARCHAR, competition_id VARCHAR, season_id VARCHAR, family VARCHAR, "
    "home_odds DOUBLE, draw_odds DOUBLE, away_odds DOUBLE, observed_at TIMESTAMPTZ",
    "team_statistics": "match_id VARCHAR, team_id VARCHAR, competition_id VARCHAR, "
    "season_id VARCHAR, expected_goals DOUBLE, goals_prevented DOUBLE, shots_total INTEGER, "
    "shots_on_goal INTEGER, shots_off_goal INTEGER, shots_blocked INTEGER, "
    "shots_inside_box INTEGER, shots_outside_box INTEGER, corners INTEGER, offsides INTEGER, "
    "fouls INTEGER, yellow_cards INTEGER, red_cards INTEGER, goalkeeper_saves INTEGER, "
    "passes_total INTEGER, passes_accurate INTEGER, possession DOUBLE, api_id BIGINT",
    "standings": "competition_id VARCHAR, season_id VARCHAR, team_id VARCHAR, rank INTEGER, "
    "points INTEGER, played INTEGER, wins INTEGER, draws INTEGER, losses INTEGER, "
    "goals_for INTEGER, goals_against INTEGER, goal_difference INTEGER, "
    "group_name VARCHAR, description VARCHAR, updated_at TIMESTAMPTZ",
}
KEYS = {
    "competition_seasons": ["competition_id", "season_id"],
    "teams": ["team_id"],
    "fixtures": ["match_id"],
    "players": ["player_id"],
    "memberships": ["player_id", "team_id", "season_id", "basis"],
    "appearances": ["match_id", "player_id", "team_id"],
    "availability": ["player_id", "fpl_code", "scope", "status", "start_date", "reason"],
    "transfers": ["player_id", "transfer_date", "from_team_id", "to_team_id", "transfer_type"],
    "team_process": ["match_id", "team_id"],
    "player_process": ["match_id", "understat_id"],
    "odds": ["match_id", "family"],
    "team_statistics": ["match_id", "team_id"],
    "standings": ["competition_id", "season_id", "team_id"],
}


def timestamp(value):
    result = datetime.fromisoformat(value) if isinstance(value, str) else value
    if result.tzinfo is None:
        raise ValueError("Timestamp requires timezone")
    return result.astimezone(UTC)


def publish(root, request, tables):
    root = Path(root)
    batch = sha256_bytes(json_bytes({"request": request, "tables": tables}))
    destination = root / "manifests" / f"{batch}.json"
    if destination.exists():
        return json.loads(destination.read_text())
    files = []
    with duckdb.connect() as con:
        con.execute(SESSION_TIME_ZONE)
        for table, rows in sorted(tables.items()):
            if not rows:
                continue
            if table not in SCHEMAS:
                raise ValueError(f"Unknown canonical table: {table}")
            con.execute(f"CREATE TABLE records ({SCHEMAS[table]}, {COMMON})")
            columns = [r[0] for r in con.execute("DESCRIBE records").fetchall()]
            common = {
                k: request[k]
                for k in ("provider", "retrieved_at", "evidence_basis", "source_sha256")
            }
            common["normalization_version"] = request.get("normalization_version", 1)
            values = [{**common, **r} for r in rows]
            for row in values:
                unknown = set(row) - set(columns)
                if unknown:
                    raise ValueError(f"Unknown {table} columns: {unknown}")
            con.execute(
                "INSERT INTO records SELECT unnest(from_json_strict(?, ?), recursive := true)",
                [
                    json.dumps([{c: r.get(c) for c in columns} for r in values], allow_nan=False),
                    json.dumps(
                        [{c[1]: c[2] for c in con.execute("PRAGMA table_info(records)").fetchall()}]
                    ),
                ],
            )
            invalid = {
                "fixtures": "home_team_id=away_team_id OR home_team_id IS NULL "
                "OR away_team_id IS NULL OR (status='finished' AND (home_goals IS NULL "
                "OR away_goals IS NULL OR home_goals<0 OR away_goals<0))",
                "appearances": "player_id IS NULL OR minutes<0 OR minutes>120 "
                "OR starts NOT IN (0,1)",
                "players": "player_id IS NULL",
                "team_process": "xg<0 OR NOT isfinite(xg) OR shots<0 OR shots_on_target<0 "
                "OR shots_on_target>shots",
                "player_process": "xg<0 OR NOT isfinite(xg) OR xa<0 OR NOT isfinite(xa)",
                "odds": "home_odds<=1 OR draw_odds<=1 OR away_odds<=1 "
                "OR NOT isfinite(home_odds) OR NOT isfinite(draw_odds) "
                "OR NOT isfinite(away_odds)",
                "team_statistics": "team_id IS NULL OR match_id IS NULL "
                "OR expected_goals<0 OR shots_total<0 OR shots_on_goal<0 "
                "OR possession<0 OR possession>100 "
                "OR shots_on_goal>shots_total OR passes_accurate>passes_total",
                "standings": "team_id IS NULL OR rank<1 OR played<0 OR wins<0 OR draws<0 "
                "OR losses<0 OR goals_for<0 OR goals_against<0 "
                "OR wins+draws+losses<>played "
                "OR goal_difference<>goals_for-goals_against",
            }.get(table)
            if invalid and con.execute(f"SELECT 1 FROM records WHERE {invalid} LIMIT 1").fetchone():
                raise ValueError(f"Invalid canonical {table} data")
            keys = ",".join(KEYS[table])
            if con.execute(
                f"SELECT 1 FROM records GROUP BY {keys} HAVING count(*)>1 LIMIT 1"
            ).fetchone():
                raise ValueError(f"Contradictory or duplicate {table} keys")
            partitions = [("all", "all")]
            if "competition_id" in columns and "season_id" in columns:
                partitions = con.execute(
                    "SELECT DISTINCT competition_id, season_id FROM records ORDER BY 1,2"
                ).fetchall()
            for competition, season in partitions:
                parent = root / "parquet" / table
                if competition != "all":
                    parent /= f"competition_id={competition}/season_id={season}"
                parent.mkdir(parents=True, exist_ok=True)
                path = parent / f"{batch}.parquet"
                temp = path.with_suffix(".tmp")
                where = (
                    ""
                    if competition == "all"
                    else " WHERE competition_id IS NOT DISTINCT FROM ? "
                    "AND season_id IS NOT DISTINCT FROM ?"
                )
                params = [] if competition == "all" else [competition, season]
                query = f"SELECT * FROM records{where} ORDER BY {keys}"
                con.execute(
                    f"COPY ({query}) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(temp), *params]
                )
                temp.replace(path)
                files.append(
                    {"table": table, "path": str(path.relative_to(root)), "sha256": file_hash(path)}
                )
            con.execute("DROP TABLE records")
    manifest = {
        "batch_id": batch,
        "request": request,
        "files": files,
        "rows": {t: len(r) for t, r in tables.items()},
    }
    write_immutable(destination, json_bytes(manifest))
    return manifest


class Dataset:
    def __init__(self, root=Path("data"), cutoff=None, manifests=None, store=None):
        self.root = Path(root)
        self.store = store if store is not None else r2_store_if_configured("R2_DATA_BUCKET")
        self.cutoff = timestamp(cutoff) if cutoff is not None else None
        if manifests is None:
            local = [
                json.loads(p.read_text()) for p in sorted((self.root / "manifests").glob("*.json"))
            ]
            catalog = self.store.get_json("state/manifests.json", {}) if self.store else {}
            remote = catalog.get("manifests", [])
            manifests = list({m["batch_id"]: m for m in [*remote, *local]}.values())
        self.manifests = manifests
        self.manifests = [
            m
            for m in self.manifests
            if self.cutoff is None
            or m.get("covers_history")
            or timestamp(m["request"]["retrieved_at"]) <= self.cutoff
        ]
        self.con = duckdb.connect()
        self.con.execute(SESSION_TIME_ZONE)
        if self.store:
            self.store.configure_duckdb(self.con)
        for table, schema in SCHEMAS.items():
            paths = []
            for manifest in self.manifests:
                for file in manifest["files"]:
                    if file["table"] != table:
                        continue
                    local_path = self.root / file["path"]
                    if local_path.exists():
                        paths.append(str(local_path))
                    elif self.store:
                        paths.append(self.store.uri(file["path"]))
                    else:
                        paths.append(str(local_path))
            if paths:
                self.con.execute(f"CREATE TABLE {table}_empty ({schema}, {COMMON})")
                self.con.read_parquet(
                    paths, hive_partitioning=False, union_by_name=True
                ).create_view(f"{table}_retained")
                retained = (
                    f"SELECT * FROM {table}_retained"
                    if self.cutoff is None
                    else f"SELECT * FROM {table}_retained WHERE retrieved_at <= "
                    f"TIMESTAMPTZ '{self.cutoff.isoformat()}'"
                )
                self.con.execute(
                    f"CREATE VIEW {table}_observations AS {retained} "
                    f"UNION ALL BY NAME SELECT * FROM {table}_empty"
                )
            else:
                self.con.execute(f"CREATE TABLE {table}_observations ({schema}, {COMMON})")
            keys = ",".join(["provider", *KEYS[table]])
            if table == "players":
                columns = [c.split()[0] for c in (schema + ", " + COMMON).split(", ")]
                selections = ["player_id"] + [
                    (
                        "arg_max(name, (birth_date IS NOT NULL, "
                        "retrieved_at, source_sha256)) AS name"
                        if c == "name"
                        else f"arg_max({c}, (retrieved_at, source_sha256)) AS {c}"
                    )
                    for c in columns
                    if c != "player_id"
                ]
                self.con.execute(
                    "CREATE VIEW players AS SELECT "
                    + ", ".join(selections)
                    + " FROM players_observations GROUP BY player_id"
                )
            else:
                self.con.execute(
                    f"CREATE VIEW {table} AS SELECT * FROM {table}_observations "
                    f"QUALIFY row_number() OVER (PARTITION BY {keys} "
                    "ORDER BY retrieved_at DESC, source_sha256 DESC, "
                    "normalization_version DESC NULLS LAST)=1"
                )

    def close(self):
        self.con.close()

    def rows(self, sql, parameters=None):
        result = self.con.execute(sql, parameters or [])
        columns = [c[0] for c in result.description]
        return [dict(zip(columns, r, strict=True)) for r in result.fetchall()]

    def provenance(self):
        return {
            "batches": [m["batch_id"] for m in self.manifests],
            "cutoff": self.cutoff.isoformat() if self.cutoff else None,
            "files": [f for m in self.manifests for f in m["files"]],
        }

    def verify(self):
        for m in self.manifests:
            for f in m["files"]:
                local = self.root / f["path"]
                digest = (
                    file_hash(local)
                    if local.exists()
                    else sha256_bytes(self.store.get_bytes(f["path"]))
                    if self.store
                    else None
                )
                if digest != f["sha256"]:
                    raise ValueError(f"Parquet checksum mismatch: {f['path']}")

    def fixtures(self):
        grouped = defaultdict(list)
        for r in self.rows("SELECT * FROM fixtures ORDER BY retrieved_at, provider"):
            grouped[r["match_id"]].append(r)
        result = []
        for key, rows in grouped.items():
            identity = {
                (r["home_team_id"], r["away_team_id"], r["competition_id"], r["season_id"])
                for r in rows
            }
            scores = {(r["home_goals"], r["away_goals"]) for r in rows if r["status"] == "finished"}
            dates = {r["match_date"] for r in rows if r["status"] == "finished"}
            if len(identity) != 1 or len(scores) > 1 or len(dates) > 1:
                raise ValueError(f"Contradictory fixture data: {key}")
            row = next((r for r in reversed(rows) if r["provider"] == "api_football"), rows[-1])
            if scores and row["status"] != "finished":
                row = dict(
                    row,
                    match_date=row["match_date"] or next(iter(dates)),
                    status="finished",
                    home_goals=next(iter(scores))[0],
                    away_goals=next(iter(scores))[1],
                )
            result.append(row)
        return sorted(result, key=lambda r: (r["match_date"] or date.max, r["match_id"]))

    def matches(self):
        return [
            Match(
                Fixture(
                    r["match_id"],
                    r["competition_id"],
                    r["season_id"],
                    r["match_date"],
                    r["home_team_id"],
                    r["away_team_id"],
                ),
                r["home_goals"],
                r["away_goals"],
                r["source_sha256"],
                r["source_row"] or 0,
                r["source_time"] or "",
            )
            for r in self.fixtures()
            if r["status"] == "finished" and r["stage"] == "regular"
        ]

    def xg_observations(self):
        """Team xG that M7 observes: API-Football, and Understat before API-Football coverage."""
        understat = self.rows(
            "SELECT match_id, team_id, xg, source_sha256, evidence_basis FROM team_process "
            "WHERE xg IS NOT NULL"
        )
        api = self.rows(
            "SELECT match_id, team_id, expected_goals AS xg, source_sha256, evidence_basis "
            "FROM team_statistics WHERE expected_goals IS NOT NULL "
            "QUALIFY row_number() OVER (PARTITION BY match_id, team_id ORDER BY retrieved_at DESC)=1"
        )
        matches = self.matches()
        return select_xg_observations(match_xg(matches, understat), match_xg(matches, api))

    def player_history(self):
        return self.rows(
            "SELECT a.*, p.name AS player_name FROM appearances a LEFT JOIN "
            "(SELECT * FROM players QUALIFY row_number() OVER "
            "(PARTITION BY player_id ORDER BY retrieved_at DESC)=1) p USING(player_id) "
            "WHERE a.minutes IS NOT NULL ORDER BY kickoff_time, player_id"
        )


def load_dataset(directory=Path("data"), cutoff=None):
    data = Dataset(directory, cutoff)
    try:
        return data.matches(), data.rows("SELECT * FROM odds"), data.provenance()
    finally:
        data.close()


def match_xg(matches, rows):
    """One observation for each match with xG for both teams."""
    values = {(r["match_id"], r["team_id"]): r for r in rows}
    result = []
    for match in matches:
        f = match.fixture
        h, a = (values.get((f.match_id, t)) for t in (f.home_team_id, f.away_team_id))
        if h is None or a is None:
            continue
        result.append(
            {
                "match_id": f.match_id,
                "season_id": f.season_id,
                "match_date": str(f.match_date),
                "home_team_id": f.home_team_id,
                "away_team_id": f.away_team_id,
                "home_goals": match.home_goals,
                "away_goals": match.away_goals,
                "home_xg": float(h["xg"]),
                "away_xg": float(a["xg"]),
                "source_sha256": h["source_sha256"],
                "available_on": str(match.available_on),
                "availability_basis": h["evidence_basis"],
            }
        )
    return result


def select_xg_observations(understat, api):
    """API-Football xG from its first match date in a competition, and Understat before it.

    A match without xG stays in the filter and updates the state on goals only.
    """
    first = {}
    for row in api:
        competition = row["match_id"].split(":")[0]
        first[competition] = min(first.get(competition, row["match_date"]), row["match_date"])
    earlier = [
        r for r in understat if r["match_date"] < first.get(r["match_id"].split(":")[0], "9")
    ]
    return sorted([*earlier, *api], key=lambda row: (row["match_date"], row["match_id"]))


def load_player_history(root=Path("data")):
    data = Dataset(root)
    try:
        return data.player_history()
    finally:
        data.close()
