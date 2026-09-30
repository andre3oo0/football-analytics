"""Orchestrate ingestion: for each competition and endpoint, fetch (cache-first),
validate, then upsert into the DuckDB raw schema.

Usage:
    python -m ingestion.run                        # cache-first; no API calls if cached
    python -m ingestion.run --refresh              # re-fetch live data from the API
    python -m ingestion.run --season 2024          # a past season (2024/25)
    python -m ingestion.run --competitions PL SA   # subset (default: every seed row)
    python -m ingestion.run --cache-dir tests/fixtures/raw   # load committed fixtures

The whole run is one transaction. If any endpoint fails, nothing is committed,
the failure is recorded in raw._load_runs, and the process exits 1. Re-running
is cheap because every response that did succeed is already cached on disk.

The API key is read from FOOTBALL_DATA_API_KEY (a local .env is loaded if
present). It is never passed on the command line.
"""

from __future__ import annotations

import argparse
import logging
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv

from .api_client import FootballDataClient, ResourceNotFound
from .config import (
    API_KEY_ENV_VAR,
    COMPETITIONS,
    DEFAULT_DB_PATH,
    ENDPOINTS,
    RAW_CACHE_DIR,
)
from .loader import LoadResult, RawLoader
from .validation import VALIDATORS

log = logging.getLogger("ingestion")

_LOADERS = {
    "teams": RawLoader.load_teams,
    "matches": RawLoader.load_matches,
    "standings": RawLoader.load_standings,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest football-data.org into DuckDB raw schema.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="DuckDB file path.")
    parser.add_argument("--cache-dir", default=str(RAW_CACHE_DIR),
                        help="Folder of cached JSON responses (default: data/raw).")
    parser.add_argument("--refresh", action="store_true",
                        help="Re-fetch from the API even if a cached response exists.")
    parser.add_argument("--competitions", nargs="+", metavar="CODE",
                        help="Subset of competition codes to ingest (default: all).")
    parser.add_argument("--endpoints", nargs="+", metavar="EP", choices=ENDPOINTS,
                        help="Subset of endpoints (default: teams matches standings).")
    parser.add_argument("--season", type=int, metavar="YEAR",
                        help="Season start year (e.g. 2024 for 2024/25). Default: the API's "
                             "current season. Cached under a season-scoped filename.")
    return parser.parse_args(argv)


def configure_logging(run_id: str) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s %(levelname)-7s [{run_id}] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        force=True,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_id = uuid.uuid4().hex[:12]
    configure_logging(run_id)
    load_dotenv()
    api_key = os.environ.get(API_KEY_ENV_VAR)

    competitions = COMPETITIONS
    if args.competitions:
        wanted = {c.upper() for c in args.competitions}
        unknown = wanted - {c.code for c in COMPETITIONS}
        if unknown:
            log.error("unknown competition code(s): %s", " ".join(sorted(unknown)))
            return 2
        competitions = [c for c in COMPETITIONS if c.code in wanted]
    endpoints = args.endpoints or ENDPOINTS

    client = FootballDataClient(api_key, Path(args.cache_dir))
    log.info("warehouse=%s cache=%s mode=%s season=%s endpoints=%s api_key=%s",
             args.db, args.cache_dir, "refresh" if args.refresh else "cache-first",
             args.season or "current", ",".join(endpoints), "yes" if api_key else "no")

    failures: list[str] = []
    totals = LoadResult()
    loaded = 0

    with RawLoader(args.db) as loader:
        loader.create_schema()
        loader.begin()

        for comp in competitions:
            for endpoint in endpoints:
                try:
                    response = client.get_competition_resource(
                        comp.code, endpoint, season=args.season,
                        force_refresh=args.refresh, validate=VALIDATORS[endpoint],
                    )
                    source_file = client.cache_path_for(comp.code, endpoint, args.season).name
                    result = _LOADERS[endpoint](loader, response, comp.code, source_file)
                except ResourceNotFound:
                    # e.g. a competition with no standings table for a season.
                    log.info("%-4s %-10s not available (404), skipping", comp.code, endpoint)
                    continue
                except Exception as exc:  # noqa: BLE001 - report every failure, then roll back
                    failures.append(f"{comp.code}/{endpoint}: {exc}")
                    log.error("%-4s %-10s FAILED: %s", comp.code, endpoint, exc)
                    continue
                loaded += 1
                totals.received += result.received
                totals.changed += result.changed
                totals.deleted += result.deleted
                log.info("%-4s %-10s received %4d, changed %4d, deleted %d",
                         comp.code, endpoint, result.received, result.changed, result.deleted)

        if failures:
            loader.rollback()
            log.error("%d endpoint(s) failed; rolled back, nothing committed", len(failures))
        else:
            loader.commit()

        loader.record_run(
            run_id=run_id,
            status="failed" if failures else "success",
            season=args.season,
            refresh=args.refresh,
            endpoints_loaded=0 if failures else loaded,
            totals=LoadResult() if failures else totals,
            failures=failures,
        )
        counts = loader.row_counts()

    log.info("raw row counts: %s", ", ".join(f"{t}={n}" for t, n in counts.items()))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
