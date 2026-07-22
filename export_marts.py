"""Export the curated mart tables to Parquet for Power BI.

Opens the DuckDB warehouse read-only and writes one Parquet file per mart into
exports/. Only the marts are exported (not raw/staging/intermediate): this is
the serving layer, not a database dump. Row counts are printed as it goes so a
run checks itself.
"""

from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parent
DB_PATH = REPO_ROOT / "data" / "football.duckdb"      # same file the dbt profile uses
EXPORT_DIR = REPO_ROOT / "exports"
SCHEMA = "marts"                                        # where the schema-name macro puts them

TABLES = [
    "fact_matches",
    "fact_standings",
    "dim_teams",
    "dim_competitions",
    "dim_seasons",
]


def main() -> None:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    # read_only so exporting can never lock out or mutate the warehouse.
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        print(f"warehouse : {DB_PATH}")
        print(f"exporting {SCHEMA}.* to {EXPORT_DIR}")
        for table in TABLES:
            n = con.execute(f"SELECT count(*) FROM {SCHEMA}.{table}").fetchone()[0]
            out_path = (EXPORT_DIR / f"{table}.parquet").as_posix()
            con.execute(f"COPY {SCHEMA}.{table} TO '{out_path}' (FORMAT PARQUET)")
            print(f"  {table:<18} {n:>6} rows -> {table}.parquet")
    finally:
        con.close()


if __name__ == "__main__":
    main()
