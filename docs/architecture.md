# Architecture

## Overview

A small ELT pipeline. Python extracts and loads: it fetches from the API,
validates and caches each response, and lands it in DuckDB with as little
interpretation as possible. dbt does every transformation, in SQL with tests
and docs.

## Data flow

```
football-data.org API (REST v4, free tier: 10 requests/minute)
   |
   |  ingestion/ (Python)
   |    throttle to ~8 requests/minute; retry 429, 5xx and network errors
   |    validate each response, then cache it to data/raw/*.json
   v
DuckDB raw schema
   |    upsert by primary key, rewriting only rows whose payload changed
   |    delete matches that left a season's fixture list
   |    one transaction per run, logged in raw._load_runs
   |
   |  dbt (dbt-duckdb)
   v
staging schema        views, 1:1 with raw
intermediate schema   views
marts schema          tables with enforced contracts
   |
   +--> dbt tests and dbt docs
   +--> export_marts.py -> exports/*.parquet (read-only)
```

## Layers

| Layer | Schema | Materialisation | Models |
|-------|--------|-----------------|--------|
| Raw | `raw` | tables (Python) | `teams`, `matches`, `standings`, `_load_runs` |
| Seed | `main` | table | `seed_competitions` |
| Staging | `staging` | views | `stg_teams`, `stg_matches`, `stg_standings` |
| Intermediate | `intermediate` | views | `int_seasons`, `int_matches` |
| Marts | `marts` | tables (`fact_standings` incremental) | 4 dimensions, 3 facts |

Staging renames, casts, unpacks JSON and normalises values (the match `status`
field). Anything more belongs in intermediate or marts. `stg_standings` feeds no
model; the reconciliation test reads it.

![dbt lineage](lineage_dag.svg)

For the interactive graph, run `dbt docs generate --profiles-dir .` and
`dbt docs serve --profiles-dir .` from `dbt/`.

## The warehouse

One DuckDB file, `data/football.duckdb` by default. dbt reads the path from
`DBT_DUCKDB_PATH` (relative to `dbt/`), and `export_marts.py` resolves it the
same way. DuckDB names the catalog after the file stem, so the catalog is
`football`; the source definition depends on that name. The file is
git-ignored and can be rebuilt from the cached JSON.

DuckDB allows one writer at a time. Every step (ingest, each dbt command, the
export) is its own process that opens and closes the file, and steps run one
after another. The export opens the file read-only. A second process that
tries to write while another holds the file will block or fail with a lock
error.

## Where state lives

| Where | What |
|-------|------|
| `data/raw/*.json` | every validated API response, one file per competition, endpoint and season |
| `data/football.duckdb` | raw tables, the run log, and everything dbt builds |
| `tests/fixtures/raw/` | one committed season for running without an API key |
| GitHub Actions cache | the nightly pipeline's copy of the two above, carried between runs |

Locally, the JSON cache is the durable part: delete the DuckDB file and a
cache-first ingest rebuilds raw without any API calls. In GitHub Actions both
are restored from the cache at the start of a run and saved again only when the
run succeeds; see [orchestration.md](orchestration.md).

## Technology

- Python 3.11+ for ingestion: `requests`, `python-dotenv`, `duckdb`, `truststore`.
- DuckDB as the warehouse.
- dbt-duckdb for transformation, tests and docs.
- pytest and ruff for the Python code.
- GitHub Actions for CI and the nightly pipeline, started by an external cron
  service with GitHub's schedule as a fallback.

Version ranges are in `requirements.txt` and `requirements-dev.txt`; the exact
versions CI and the pipeline install are in `requirements.lock` and
`requirements-dev.lock`, for the Python version in `.python-version`.
