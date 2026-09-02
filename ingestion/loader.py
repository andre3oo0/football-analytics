"""Load cached API responses into the DuckDB raw schema.

The load is idempotent because it upserts by natural key, never blind-appends,
and that natural key is enforced by a table-level PRIMARY KEY, so the guarantee
lives in the schema rather than in convention:

    raw.teams      PK (team_id)
    raw.matches    PK (match_id)
    raw.standings  PK (competition_code, season_id, team_id, matchday, standing_type)

Every load does INSERT ... ON CONFLICT (<pk>) DO UPDATE, so re-loading a record
replaces the existing row. A match that moves SCHEDULED -> FINISHED overwrites
its old row; there is exactly one current row per natural key. I deliberately
don't keep raw history/SCD here. The only time-series we want (standings by
matchday) is derived downstream in fact_standings.

Ingestion stays thin: each raw row is just the natural key (typed, for the
constraint) plus the untouched API payload as JSON. All field-level work is dbt's
job.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import duckdb

# The DDL is where idempotency actually comes from: the PRIMARY KEYs below make
# a duplicate impossible even if the loader is called wrongly.
_DDL: list[str] = [
    "CREATE SCHEMA IF NOT EXISTS raw;",
    """
    CREATE TABLE IF NOT EXISTS raw.teams (
        team_id           BIGINT      NOT NULL,
        competition_code  VARCHAR     NOT NULL,
        payload           JSON        NOT NULL,
        _source_file      VARCHAR,
        _loaded_at        TIMESTAMP,
        PRIMARY KEY (team_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS raw.matches (
        match_id          BIGINT      NOT NULL,
        competition_code  VARCHAR     NOT NULL,
        payload           JSON        NOT NULL,
        _source_file      VARCHAR,
        _loaded_at        TIMESTAMP,
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
        _loaded_at        TIMESTAMP,
        PRIMARY KEY (competition_code, season_id, team_id, matchday, standing_type)
    );
    """,
]


class RawLoader:
    """Owns a DuckDB connection and the upsert logic for the raw schema."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(self.db_path)

    def create_schema(self) -> None:
        for stmt in _DDL:
            self.con.execute(stmt)

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> "RawLoader":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def row_counts(self) -> dict[str, int]:
        return {
            table: self.con.execute(
                f"SELECT count(*) FROM raw.{table}"
            ).fetchone()[0]
            for table in ("teams", "matches", "standings")
        }

    # One load method per endpoint; each returns how many rows it upserted.

    def load_teams(self, response: dict, competition_code: str, source_file: str) -> int:
        now = datetime.now()
        rows = [
            (int(team["id"]), competition_code, json.dumps(team), source_file, now)
            for team in response.get("teams", [])
        ]
        self.con.executemany(
            """
            INSERT INTO raw.teams
                (team_id, competition_code, payload, _source_file, _loaded_at)
            VALUES (?, ?, ?::JSON, ?, ?)
            ON CONFLICT (team_id) DO UPDATE SET
                competition_code = excluded.competition_code,
                payload          = excluded.payload,
                _source_file     = excluded._source_file,
                _loaded_at       = excluded._loaded_at;
            """,
            rows,
        )
        return len(rows)

    def load_matches(self, response: dict, competition_code: str, source_file: str) -> int:
        now = datetime.now()
        rows = [
            (int(match["id"]), competition_code, json.dumps(match), source_file, now)
            for match in response.get("matches", [])
        ]
        self.con.executemany(
            """
            INSERT INTO raw.matches
                (match_id, competition_code, payload, _source_file, _loaded_at)
            VALUES (?, ?, ?::JSON, ?, ?)
            ON CONFLICT (match_id) DO UPDATE SET
                competition_code = excluded.competition_code,
                payload          = excluded.payload,
                _source_file     = excluded._source_file,
                _loaded_at       = excluded._loaded_at;
            """,
            rows,
        )
        return len(rows)

    def load_standings(self, response: dict, competition_code: str, source_file: str) -> int:
        """Explode the standings snapshot to one row per team per table type.

        A standings response is a single snapshot at season.currentMatchday, and
        it can carry several tables: TOTAL and (mid-season) HOME/AWAY, plus one
        table per group where a competition has groups. I land every type the
        source returns so raw stays a faithful copy. Picking TOTAL is a decision
        I make later in dbt (stg_standings), where it's explicit, not silently at
        ingest, which is why standing_type is part of the key.
        """
        now = datetime.now()
        season = response.get("season") or {}
        season_id = season.get("id")
        # currentMatchday can be null (e.g. before a competition starts). The PK
        # column is NOT NULL, so coalesce to 0 and let dbt interpret it.
        matchday = season.get("currentMatchday") or 0

        rows = []
        for entry in response.get("standings", []):
            standing_type = entry.get("type")
            stage = entry.get("stage")
            group_name = entry.get("group")
            for line in entry.get("table", []):
                team_id = line.get("team", {}).get("id")
                if team_id is None or season_id is None or standing_type is None:
                    continue  # can't form the natural key, so skip it defensively
                rows.append(
                    (
                        competition_code,
                        int(season_id),
                        int(team_id),
                        int(matchday),
                        standing_type,
                        stage,
                        group_name,
                        json.dumps(line),
                        source_file,
                        now,
                    )
                )

        self.con.executemany(
            """
            INSERT INTO raw.standings
                (competition_code, season_id, team_id, matchday, standing_type,
                 stage, group_name, payload, _source_file, _loaded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?::JSON, ?, ?)
            ON CONFLICT (competition_code, season_id, team_id, matchday, standing_type) DO UPDATE SET
                stage        = excluded.stage,
                group_name   = excluded.group_name,
                payload      = excluded.payload,
                _source_file = excluded._source_file,
                _loaded_at   = excluded._loaded_at;
            """,
            rows,
        )
        return len(rows)
