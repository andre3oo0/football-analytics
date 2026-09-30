# Ingestion

The `ingestion/` package fetches from football-data.org, validates and caches
each response, and loads it into the DuckDB `raw` schema. It lands the payload
keyed by its natural key and leaves interpretation to dbt.

## Modules

| File | Responsibility |
|------|----------------|
| `config.py` | Paths, API settings, the rate-limit budget, and `load_competitions()`. |
| `validation.py` | Shape checks per endpoint; raises `InvalidResponse`. |
| `api_client.py` | The rate-limited, cache-first HTTP client. |
| `loader.py` | The raw DDL, the change-only upsert, and the run log. |
| `run.py` | The CLI, `python -m ingestion.run`. |

Everything logs through the `logging` module. Each line carries the run id,
which is also the `run_id` in `raw._load_runs`.

## Competitions

`config.load_competitions()` reads `dbt/seeds/seed_competitions.csv`
(`competition_code`, `competition_name`). The same seed builds
`dim_competitions`, so adding a league is one row in that file. Endpoints per
competition are `teams`, `matches` and `standings`.

## The API client

### Rate limit and retries

The free tier allows 10 requests a minute. The client leaves at least 7.5
seconds between real network calls (about 8 a minute). It retries, up to
`MAX_RETRIES` (5) attempts:

- HTTP 429, waiting for `Retry-After` plus one second when the header is
  present, otherwise exponential backoff;
- 5xx responses;
- connection errors and timeouts (30-second request timeout).

Backoff is `5s * 2^attempt` plus up to 25% random jitter. A 404 raises
`ResourceNotFound`, which the run treats as "not available" and skips. Any
other 4xx (a bad key, a season the free tier doesn't expose) raises at once.
When retries run out the client raises `RateLimitError`.

### Cache

Every response is cached as
`<cache-dir>/<competition>_<endpoint>[_<season>].json`, for example
`PL_matches.json` for the current season and `PL_matches_2024.json` for
2024/25. Reads are cache-first: if the file exists and `--refresh` isn't set, no
request is made. With no cached file and no API key, the fetch fails.

A fetched response is validated before it is written, so a bad body is never
cached. The write goes to a temporary file in the same folder and is renamed
over the target with `os.replace`, so an interrupted write can't leave a
truncated file. Cached files are validated again on read.

### Validation

`validation.py` checks each 200 response before it is cached or loaded:

| Endpoint | Checks |
|----------|--------|
| teams | `teams` is a non-empty list; `count` (if present) equals its length; every team has an `id` |
| matches | `matches` is a non-empty list; `resultSet.count` (if present) equals its length; every match has an `id` |
| standings | `standings` is a list; `season.id` is present |

Without these checks, a 200 with an unexpected body would load zero rows and
report success, and cache-first mode would keep serving the bad file.

### TLS

`truststore` makes TLS verify against the operating system's trust store in
place of certifi's bundle. If truststore is missing or fails to inject, the
client logs it and falls back to certifi.

## The raw schema

`RawLoader.create_schema()` creates four tables. The data tables hold the
typed natural key, the untouched JSON payload, `_source_file` (the cache file
name) and `_loaded_at`.

| Table | Primary key |
|-------|-------------|
| `raw.teams` | `team_id` |
| `raw.matches` | `match_id` |
| `raw.standings` | `competition_code, season_id, team_id, matchday, standing_type` |
| `raw._load_runs` | `run_id` |

Column-level detail is in [data-dictionary.md](data-dictionary.md).

### Change-only upsert

Loads upsert on the primary key with `INSERT ... ON CONFLICT DO UPDATE`, so
reloading never duplicates a row. Before the upsert, incoming rows whose payload
is identical to the stored one are dropped. A row is therefore rewritten only
when its content changed, and `_loaded_at` means "when this content last
changed". `fact_standings` uses that as its incremental watermark.

`_loaded_at` is naive UTC: the run's start time, identical for every row a run
writes.

Rows go into DuckDB as one JSON string unpacked with `json_each` in SQL. Binding
Python lists or using `executemany` is row-at-a-time in DuckDB and far slower.

### Deletes

A matches response is the full fixture list for its season. After the upsert,
any match stored for that competition and season that is missing from the
response is deleted, and the count is logged. Teams are never deleted: a
relegated team is still referenced by earlier seasons.

A real removal is rare, so there is a limit: if one response would delete more
than `MAX_MATCH_DELETES_PER_LOAD` (5) stored matches, the loader raises
`LoadAnomaly` instead of deleting them. The run then fails and rolls back like
any other endpoint failure, and raw keeps the matches it had.

### Standings

A standings response is one snapshot at `season.currentMatchday` and can hold
several tables: TOTAL and, mid-season, HOME and AWAY. The loader keeps every
type, one row per team per type. A null `currentMatchday` (before a season
starts) is stored as 0. Rows missing a team id, season id or table type are
skipped, counted and logged.

### The run log

`raw._load_runs` gets one row per run, written after the run commits or rolls
back: start and finish time (UTC), `status` (`success` or `failed`), the season
and refresh flag, endpoints loaded, rows received, changed and deleted, and the
failure messages. For a failed run the counts are zero, because nothing was
committed. dbt's source freshness check reads this table, and the nightly
pipeline runs that check on the restored warehouse before each ingest.

## run.py

```
python -m ingestion.run [--db PATH] [--cache-dir DIR] [--refresh]
                        [--competitions CODE ...] [--endpoints EP ...]
                        [--season YEAR]
```

| Flag | Default | Meaning |
|------|---------|---------|
| `--db` | `data/football.duckdb` | DuckDB file to load into. |
| `--cache-dir` | `data/raw` | Folder of cached responses. `tests/fixtures/raw` loads the committed fixture season. |
| `--refresh` | off | Fetch from the API even when a cached response exists. |
| `--competitions` | every seed row | Subset of codes, e.g. `PL SA`. |
| `--endpoints` | `teams matches standings` | Subset of endpoints. |
| `--season` | the API's current season | Start year, e.g. `2024` for 2024/25. Sent as `?season=` and used in the cache file name. |

The API key comes from `FOOTBALL_DATA_API_KEY`, read from `.env` if present and
otherwise from the environment. It is never a command-line argument.

### One transaction per run

The run opens a transaction, loads every competition and endpoint, and commits
only if all of them succeeded. If any endpoint fails, the others still run so
every failure is reported, then everything rolls back, the failure is recorded
in `raw._load_runs`, and the process exits 1. Re-running is cheap: every
response that succeeded is already cached.

| Exit code | Meaning |
|-----------|---------|
| 0 | every endpoint loaded (404s skipped) and committed |
| 1 | at least one endpoint failed (including a `LoadAnomaly`); nothing committed |
| 2 | an unknown competition code was passed |

A run logs its settings, one line per competition and endpoint (received,
changed, deleted), and the final raw row counts.
