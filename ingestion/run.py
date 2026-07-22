"""Orchestrate ingestion: for each competition and endpoint, fetch (cache-first),
then upsert into the DuckDB raw schema.

Usage:
    python -m ingestion.run                 # cache-first; no API calls if cached
    python -m ingestion.run --refresh       # re-fetch live data from the API
    python -m ingestion.run --db path.duckdb
    python -m ingestion.run --competitions PL SA   # subset (default: all six)

The API key is read from the FOOTBALL_DATA_API_KEY environment variable, loaded
from a local .env if present. It is never passed on the command line.
"""

from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv

from .api_client import FootballDataClient
from .config import (
    API_KEY_ENV_VAR,
    COMPETITIONS,
    DEFAULT_DB_PATH,
    ENDPOINTS,
    RAW_CACHE_DIR,
)
from .loader import RawLoader

# endpoint name -> RawLoader method name
_LOADERS = {
    "teams": "load_teams",
    "matches": "load_matches",
    "standings": "load_standings",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest football-data.org into DuckDB raw schema.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="DuckDB file path.")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-fetch from the API even if a cached response exists.",
    )
    parser.add_argument(
        "--competitions",
        nargs="+",
        metavar="CODE",
        help="Subset of competition codes to ingest (default: all).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_dotenv()
    api_key = os.environ.get(API_KEY_ENV_VAR)

    competitions = COMPETITIONS
    if args.competitions:
        wanted = {c.upper() for c in args.competitions}
        competitions = [c for c in COMPETITIONS if c.code in wanted]

    client = FootballDataClient(api_key, RAW_CACHE_DIR)

    print(f"DuckDB warehouse : {args.db}")
    print(f"Raw JSON cache   : {RAW_CACHE_DIR}")
    print(f"Mode             : {'REFRESH (hit API)' if args.refresh else 'cache-first'}")
    print(f"API key present  : {'yes' if api_key else 'no (cache-only)'}")
    print("-" * 68)

    failures: list[str] = []

    with RawLoader(args.db) as loader:
        loader.create_schema()

        for comp in competitions:
            for endpoint in ENDPOINTS:
                try:
                    response = client.get_competition_resource(
                        comp.code, endpoint, force_refresh=args.refresh
                    )
                    source_file = client.cache_path_for(comp.code, endpoint).name
                    method = getattr(loader, _LOADERS[endpoint])
                    n = method(response, comp.code, source_file)
                    print(f"  {comp.code:<4} {endpoint:<10} upserted {n:>4} rows")
                except Exception as exc:  # noqa: BLE001 - report & continue
                    failures.append(f"{comp.code}/{endpoint}: {exc}")
                    print(f"  {comp.code:<4} {endpoint:<10} FAILED  ({exc})")

        print("-" * 68)
        counts = loader.row_counts()
        print("Raw table row counts:")
        for table, count in counts.items():
            print(f"  raw.{table:<10} {count:>6}")

    # Fail loudly (non-zero exit) if anything went wrong, but only after doing
    # all the work we could.
    if failures:
        print("-" * 68)
        print(f"{len(failures)} endpoint(s) FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
