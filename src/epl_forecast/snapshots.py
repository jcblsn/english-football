"""Which provider responses a reader at a cutoff has seen.

A source snapshot records that one successful retrieval covered one query scope. The row
exists even when the response held no rows, because an empty successful response is
evidence: without the snapshot a reader cannot tell "the provider listed nobody" from
"the provider was never asked".

The snapshots are canonical rows, not manifest knowledge. Canonical compaction keeps rows
and collapses request contexts, so only a canonical row survives it.

One scope has one identity at a cutoff: the latest `(retrieved_at, source_sha256)` of that
scope. Readers select rows by that identity instead of taking the latest row of each
table, so a later-retrieved response for another competition, season or team cannot
supersede the evidence of this one.
"""

SQUAD = "team_squad"
INJURIES = "competition_injuries"
FPL_AVAILABILITY = "fpl_availability"
FIXTURE_DETAIL = "fixture_detail"
SIDELINED = "player_sidelined"
TRANSFERS = "player_transfers"
TEAM_TRANSFERS = "team_transfers"

COLUMNS = (
    "scope_kind",
    "scope_key",
    "endpoint",
    "competition_id",
    "season_id",
    "team_id",
    "match_id",
    "row_count",
)


def snapshot(
    kind,
    key,
    *,
    endpoint,
    row_count,
    competition_id=None,
    season_id=None,
    team_id=None,
    match_id=None,
):
    """One canonical row that records a successful retrieval of one query scope."""
    return {
        "scope_kind": kind,
        "scope_key": str(key),
        "endpoint": endpoint,
        "competition_id": competition_id,
        "season_id": season_id,
        "team_id": team_id,
        "match_id": match_id,
        "row_count": int(row_count),
    }


def capture_of(row):
    """The retrieval that produced a canonical row, as a total order.

    Two responses retrieved at the same instant are ordered by their content hash, so the
    selection does not depend on the order in which rows reach the reader.
    """
    return row["retrieved_at"], row.get("source_sha256") or ""


def squad_scope(team_id):
    return team_id


def injury_scope(competition_id, season_id):
    return f"{competition_id}:{season_id}"


class SnapshotIndex:
    """The latest snapshot of each scope that a reader at `cutoff` has seen."""

    def __init__(self, rows=(), cutoff=None):
        self.cutoff = cutoff
        self.latest = {}
        for row in rows:
            if cutoff is not None and row["retrieved_at"] > cutoff:
                continue
            key = row["scope_kind"], row["scope_key"]
            current = self.latest.get(key)
            if current is None or capture_of(row) > capture_of(current):
                self.latest[key] = row

    def __bool__(self):
        return bool(self.latest)

    def snapshot(self, kind, key):
        return self.latest.get((kind, str(key)))

    def identity(self, kind, key):
        """The retrieval that a reader must take the rows of this scope from."""
        row = self.snapshot(kind, key)
        return None if row is None else capture_of(row)

    def covers(self, kind, key):
        """True when a successful response for this scope exists at the cutoff."""
        return self.snapshot(kind, key) is not None

    def keys(self, kind):
        return {key for scope, key in self.latest if scope == kind}

    def select(self, rows, kind, key):
        """The rows of one scope that belong to its latest snapshot, or none when unseen."""
        identity = self.identity(kind, key)
        if identity is None:
            return []
        return [row for row in rows if capture_of(row) == identity]


def snapshot_rows(data):
    """Snapshot rows from a `Dataset`, including the scopes whose response held no rows."""
    columns = ", ".join(COLUMNS)
    return data.rows(
        f"SELECT {columns}, retrieved_at, source_sha256 FROM source_snapshots_observations"
    )
