"""Export the mart tables to Parquet, the files the BI layer imports.

Opens the warehouse read-only and writes one Parquet file per mart. Only the
marts are exported (not raw/staging/intermediate): this is the serving layer,
not a database dump.

The warehouse path is resolved the same way the dbt profile resolves it:
DBT_DUCKDB_PATH if set (relative paths are relative to dbt/, as for dbt),
otherwise data/football.duckdb.

    python export_marts.py
    python export_marts.py --out exports/ --db path/to/football.duckdb
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parent
DBT_DIR = REPO_ROOT / "dbt"
SCHEMA = "marts"

TABLES = [
    "fact_matches",
    "fct_team_matches",
    "fact_standings",
    "dim_teams",
    "dim_competitions",
    "dim_seasons",
    "dim_date",
]


def default_db_path() -> Path:
    env = os.environ.get("DBT_DUCKDB_PATH")
    if env:
        path = Path(env)
        return path if path.is_absolute() else (DBT_DIR / path).resolve()
    return REPO_ROOT / "data" / "football.duckdb"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=default_db_path())
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "exports")
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    # read_only so exporting can never lock out or mutate the warehouse.
    with duckdb.connect(str(args.db), read_only=True) as con:
        print(f"warehouse : {args.db}")
        print(f"exporting {SCHEMA}.* to {args.out}")
        for table in TABLES:
            n = con.execute(f"SELECT count(*) FROM {SCHEMA}.{table}").fetchone()[0]
            out_path = (args.out / f"{table}.parquet").as_posix()
            con.execute(f"COPY {SCHEMA}.{table} TO '{out_path}' (FORMAT PARQUET)")
            print(f"  {table:<18} {n:>6} rows -> {table}.parquet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
