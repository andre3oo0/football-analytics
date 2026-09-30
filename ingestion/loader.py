"""Load cached API responses into the DuckDB raw schema.

The load is idempotent because it upserts by natural key and that key is a
table-level PRIMARY KEY, so the guarantee lives in the schema:

    raw.teams      PK (team_id)
    raw.matches    PK (match_id)
    raw.standings  PK (competition_code, season_id, team_id, matchday, standing_type)

Three rules on top of the upsert:

* A row is only rewritten when its payload actually changed, so `_loaded_at`
  means "when this content last changed", not "when a run last touched it".
  That is what makes it usable as the incremental watermark in fact_standings.
* `_loaded_at` is naive UTC (the run's start time), the same on a laptop and
  a CI runner.
* A matches response is the complete fixture list for one competition-season,
  so a match that has disappeared from it is deleted from raw. Teams are not
  deleted: a relegated team is still referenced by older seasons.

Raw keeps no history (type 1). Each row is the typed natural key plus the
untouched JSON payload; all field-level work is dbt's job.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from .config import MAX_MATCH_DELETES_PER_LOAD

log = logging.getLogger(__name__)

_DDL: list[str] = [
    "CREATE SCHEMA IF NOT EXISTS raw;",
    """
    CREATE TABLE IF NOT EXISTS raw.teams (
        team_id           BIGINT      NOT NULL,
        competition_code  VARCHAR     NOT NULL,
        payload           JSON        NOT NULL,
        _source_file      VARCHAR,
        _loaded_at        TIMESTAMP,              -- naive UTC
        PRIMARY KEY (team_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS raw.matches (
        match_id          BIGINT      NOT NULL,
        competition_code  VARCHAR     NOT NULL,
        payload           JSON        NOT NULL,
        _source_file      VARCHAR,
        _loaded_at        TIMESTAMP,              -- naive UTC
        PRIMARY KEY (match_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS raw.standings (
        competition_code  VARCHAR     NOT NULL,
        season_id         BIGINT      NOT NULL,
        team_id           BIGINT      NOT NULL,
        matchday          INTEGER     NOT NULL,
        standing_type     VARCHAR     NOT NULL,   -- API 'type': TOTAL / HOME / AWAY
        stage             VARCHAR,
        group_name        VARCHAR,
        payload           JSON        NOT NULL,
        _source_file      VARCHAR,
        _loaded_at        TIMESTAMP,              -- naive UTC
        PRIMARY KEY (competition_code, season_id, team_id, matchday, standing_type)
    );
    """,
    # One row per ingestion run, written after the run commits or rolls back.
    """
    CREATE TABLE IF NOT EXISTS raw._load_runs (
        run_id            VARCHAR     NOT NULL PRIMARY KEY,
        started_at        TIMESTAMP   NOT NULL,   -- naive UTC
        finished_at       TIMESTAMP   NOT NULL,   -- naive UTC
        status            VARCHAR     NOT NULL,   -- 'success' | 'failed'
        season            INTEGER,                -- NULL = API's current season
        refresh           BOOLEAN     NOT NULL,
        endpoints_loaded  INTEGER     NOT NULL,
        rows_received     INTEGER     NOT NULL,
        rows_changed      INTEGER     NOT NULL,
        rows_deleted      INTEGER     NOT NULL,
        failures          VARCHAR
    );
    """,
]


def utc_now() -> datetime:
    """Naive UTC timestamp, which is what the TIMESTAMP columns hold."""
    return datetime.now(UTC).replace(tzinfo=None)


def _rows_to_json(columns: list[str], rows: list[tuple]) -> str:
    """Serialise rows as a JSON array of objects; the payload stays a string."""
    def value(v):
        return v.isoformat(sep=" ") if isinstance(v, datetime) else v
    return json.dumps([{c: value(v) for c, v in zip(columns, row, strict=True)} for row in rows])


class LoadAnomaly(RuntimeError):
    """A response is well-formed but would change raw in a way that looks wrong."""


@dataclass
class LoadResult:
    received: int = 0
    changed: int = 0
    deleted: int = 0


class RawLoader:
    """Owns a DuckDB connection and the upsert logic for the raw schema."""

    def __init__(self, db_path: str | Path, loaded_at: datetime | None = None) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(self.db_path)
        self.loaded_at = loaded_at or utc_now()

    def create_schema(self) -> None:
        for stmt in _DDL:
            self.con.execute(stmt)

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> RawLoader:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # A run is one transaction: either every endpoint lands or none does.
    def begin(self) -> None:
        self.con.execute("BEGIN TRANSACTION")

    def commit(self) -> None:
        self.con.execute("COMMIT")

    def rollback(self) -> None:
        self.con.execute("ROLLBACK")

    def row_counts(self) -> dict[str, int]:
        return {
            table: self.con.execute(f"SELECT count(*) FROM raw.{table}").fetchone()[0]
            for table in ("teams", "matches", "standings")
        }

    def record_run(
        self,
        *,
        run_id: str,
        status: str,
        season: int | None,
        refresh: bool,
        endpoints_loaded: int,
        totals: LoadResult,
        failures: list[str],
    ) -> None:
        self.con.execute(
            "INSERT INTO raw._load_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                run_id, self.loaded_at, utc_now(), status, season, refresh,
                endpoints_loaded, totals.received, totals.changed, totals.deleted,
                "\n".join(failures) or None,
            ],
        )

    # --- generic change-only upsert -----------------------------------------

    def _upsert(self, table: str, columns: list[str], pk: list[str], rows: list[tuple]) -> int:
        """Upsert rows that are new or differ from what's stored; return how many."""
        if not rows:
            return 0
        cols = ", ".join(columns)
        pk_cols = ", ".join(pk)
        join = " AND ".join(f"t.{c} = i.{c}" for c in pk)
        updates = ", ".join(f"{c} = excluded.{c}" for c in columns if c not in pk)
        # Every column except the audit ones decides whether a row changed.
        compared = [c for c in columns if c not in pk and c not in ("_source_file", "_loaded_at")]
        same = " AND ".join(
            f"t.{c}::VARCHAR IS NOT DISTINCT FROM i.{c}::VARCHAR" for c in compared
        )

        # All rows go in as ONE JSON string and are unpacked in SQL; the insert
        # casts each field to the temp table's column type. Binding Python
        # lists or using executemany is row-at-a-time in DuckDB and ~1000x slower.
        self.con.execute(f"CREATE OR REPLACE TEMP TABLE _incoming AS "
                         f"SELECT {cols} FROM raw.{table} LIMIT 0")
        extract = ", ".join(f"e.value ->> '{c}'" for c in columns)
        self.con.execute(f"INSERT INTO _incoming SELECT {extract} FROM json_each(?) e",
                         [_rows_to_json(columns, rows)])
        # Drop rows identical to what's already stored.
        self.con.execute(f"""
            DELETE FROM _incoming i
            WHERE EXISTS (
                SELECT 1 FROM raw.{table} t
                WHERE {join} AND {same}
            )
        """)
        changed = self.con.execute("SELECT count(*) FROM _incoming").fetchone()[0]
        self.con.execute(f"""
            INSERT INTO raw.{table} ({cols}) SELECT {cols} FROM _incoming
            ON CONFLICT ({pk_cols}) DO UPDATE SET {updates}
        """)
        self.con.execute("DROP TABLE _incoming")
        return changed

    @staticmethod
    def _dump(obj: dict) -> str:
        return json.dumps(obj, sort_keys=True)

    # --- one load method per endpoint ---------------------------------------

    def load_teams(self, response: dict, competition_code: str, source_file: str) -> LoadResult:
        rows = [
            (int(team["id"]), competition_code, self._dump(team), source_file, self.loaded_at)
            for team in response["teams"]
        ]
        changed = self._upsert(
            "teams",
            ["team_id", "competition_code", "payload", "_source_file", "_loaded_at"],
            ["team_id"],
            rows,
        )
        return LoadResult(received=len(rows), changed=changed)

    def load_matches(self, response: dict, competition_code: str, source_file: str) -> LoadResult:
        matches = response["matches"]
        rows = [
            (int(m["id"]), competition_code, self._dump(m), source_file, self.loaded_at)
            for m in matches
        ]
        changed = self._upsert(
            "matches",
            ["match_id", "competition_code", "payload", "_source_file", "_loaded_at"],
            ["match_id"],
            rows,
        )

        # The response is the full fixture list for its season(s): anything we
        # hold for those seasons that isn't in it was removed upstream.
        season_ids = sorted({int(m["season"]["id"]) for m in matches if m.get("season")})
        match_ids = [r[0] for r in rows]
        deleted = 0
        if season_ids:
            stale = """
                FROM raw.matches
                WHERE competition_code = ?
                  AND (payload ->> '$.season.id')::BIGINT
                      IN (SELECT value::BIGINT FROM json_each(?))
                  AND match_id NOT IN (SELECT value::BIGINT FROM json_each(?))
            """
            params = [competition_code, json.dumps(season_ids), json.dumps(match_ids)]
            to_delete = self.con.execute(f"SELECT count(*) {stale}", params).fetchone()[0]
            if to_delete > MAX_MATCH_DELETES_PER_LOAD:
                raise LoadAnomaly(
                    f"{competition_code}: the response would delete {to_delete} stored "
                    f"matches (limit {MAX_MATCH_DELETES_PER_LOAD}); refusing to apply it"
                )
            deleted = len(self.con.execute(f"DELETE {stale} RETURNING match_id",
                                           params).fetchall())
            if deleted:
                log.warning("%s: deleted %d match(es) no longer returned by the API",
                            competition_code, deleted)
        return LoadResult(received=len(rows), changed=changed, deleted=deleted)

    def load_standings(self, response: dict, competition_code: str, source_file: str) -> LoadResult:
        """Explode the standings snapshot to one row per team per table type.

        A standings response is one snapshot at season.currentMatchday and can
        carry several tables: TOTAL and, mid-season, HOME/AWAY. Every type is
        landed so raw stays a faithful copy; picking TOTAL happens in dbt.
        """
        season = response.get("season") or {}
        season_id = season.get("id")
        # currentMatchday can be null before a season starts. The PK column is
        # NOT NULL, so coalesce to 0 and let dbt interpret it.
        matchday = season.get("currentMatchday") or 0

        rows, skipped = [], 0
        for entry in response["standings"]:
            standing_type = entry.get("type")
            for line in entry.get("table", []):
                team_id = (line.get("team") or {}).get("id")
                if team_id is None or season_id is None or standing_type is None:
                    skipped += 1
                    continue
                rows.append((
                    competition_code, int(season_id), int(team_id), int(matchday),
                    standing_type, entry.get("stage"), entry.get("group"),
                    self._dump(line), source_file, self.loaded_at,
                ))
        if skipped:
            log.warning("%s: skipped %d standings row(s) missing a key field",
                        competition_code, skipped)

        changed = self._upsert(
            "standings",
            ["competition_code", "season_id", "team_id", "matchday", "standing_type",
             "stage", "group_name", "payload", "_source_file", "_loaded_at"],
            ["competition_code", "season_id", "team_id", "matchday", "standing_type"],
            rows,
        )
        return LoadResult(received=len(rows), changed=changed)
