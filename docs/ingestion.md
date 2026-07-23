# Ingestion

The Python package under `ingestion/` fetches data from football-data.org,
caches each response to disk, and loads it into the DuckDB `raw` schema. It is
deliberately thin: it lands the untouched payload keyed by its natural key and
leaves all interpretation to dbt.

## Modules

| File | Responsibility |
|------|----------------|
| `config.py` | Competitions, endpoints, paths, and the rate-limit budget as plain data. |
| `api_client.py` | The rate-limited, cache-first HTTP client, plus TLS handling. |
| `loader.py` | The `raw` schema DDL and the upsert-by-natural-key load methods. |
| `run.py` | The CLI that ties it together (`python -m ingestion.run`). |

## config.py

Holds constants only, no logic:

- `COMPETITIONS`: the six competitions (PL, PD, BL1, SA, FL1 as LEAGUE; WC as
  TOURNAMENT), each a small dataclass of `code`, `name`, `competition_type`.
- `ENDPOINTS`: `["teams", "matches", "standings"]`.
- `BASE_URL`, `API_KEY_ENV_VAR`.
- Rate-limit budget: `MIN_SECONDS_BETWEEN_REQUESTS = 7.5` (about 8/min against
  the 10/min cap), `MAX_RETRIES = 5`, `BACKOFF_BASE_SECONDS = 5.0`.
- Paths: `DATA_DIR`, `RAW_CACHE_DIR` (`data/raw`), `DEFAULT_DB_PATH`
  (`data/football.duckdb`).

## api_client.py

`FootballDataClient` is responsible for two guarantees.

### Never get IP-banned

- A minimum gap of 7.5 seconds is enforced between real network calls, so the
  rate never exceeds roughly 8 per minute.
- On HTTP 429 it backs off, preferring the server's `Retry-After` header and
  falling back to exponential backoff (`BACKOFF_BASE_SECONDS * 2^attempt`), up
  to `MAX_RETRIES`.
- 5xx responses are retried with the same exponential backoff. Other 4xx (a bad
  key, an unknown competition) raise immediately; there is no point retrying.

### Never hit the API when it isn't needed

- Every response is written to `data/raw/` as JSON before it is returned, so the
  loader always reads a persisted file.
- Reads are cache-first: if the cache file exists and `force_refresh` is false,
  the cached JSON is returned and no network call happens. This makes local
  re-runs free and keeps you safely under the rate limit during development.

### Cache file naming

`data/raw/<competition>_<endpoint>[_<season>].json`, for example
`PL_matches.json` for the current season and `PL_matches_2024.json` for the
2024/25 backfill. The season suffix means a historical pull never overwrites the
live cache.

### TLS

On construction the client calls `truststore.inject_into_ssl()` so verification
uses the OS trust store. This keeps verification on behind an SSL-inspecting
proxy (which presents a locally trusted root CA that certifi does not know) and
is a harmless no-op on a normal network or CI runner. It never disables
verification.

## loader.py

`RawLoader` owns a DuckDB connection and the upsert logic.

### The DDL is the idempotency guarantee

Each raw table declares its natural key as a `PRIMARY KEY`, so a duplicate is
impossible at the storage level, not just by convention:

- `raw.teams` — `PRIMARY KEY (team_id)`
- `raw.matches` — `PRIMARY KEY (match_id)`
- `raw.standings` — `PRIMARY KEY (competition_code, season_id, team_id, matchday, standing_type)`

Every raw row is the natural key (typed, for the constraint) plus the untouched
payload as `JSON`, plus `_source_file` and `_loaded_at`.

### Upsert semantics

Loads use `INSERT ... ON CONFLICT (<pk>) DO UPDATE`. Re-loading a record replaces
the existing row, so:

- Running ingestion twice yields the same raw state, never duplicates.
- A match that moves from `SCHEDULED` to `FINISHED` overwrites its old row.
- There is exactly one current row per natural key. Raw does not keep history or
  SCDs. The only time series we want (standings by matchday) is derived
  downstream in `fact_standings`.

### Standings are exploded, all types kept

A standings response is one snapshot at `season.currentMatchday` and can contain
several tables: `TOTAL` and, mid-season, `HOME`/`AWAY`, plus one table per group
for a tournament. The loader lands every type the source returns (hence
`standing_type` in the key) so raw stays a faithful copy. `currentMatchday` can
be null before a tournament starts; the PK column is `NOT NULL`, so it is
coalesced to 0.

## run.py — CLI reference

```
python -m ingestion.run [--db PATH] [--refresh]
                        [--competitions CODE ...]
                        [--endpoints EP ...]
                        [--season YEAR]
```

| Flag | Default | Meaning |
|------|---------|---------|
| `--db` | `data/football.duckdb` | Path to the DuckDB file to load into. |
| `--refresh` | off | Re-fetch from the API even if a cached response exists. |
| `--competitions` | all six | Subset of competition codes (e.g. `PL SA`). |
| `--endpoints` | teams matches standings | Subset of endpoints. |
| `--season` | current | Season start year (e.g. `2024` for 2024/25). Uses the API's `?season=` filter and a season-scoped cache filename. |

The API key is read from `FOOTBALL_DATA_API_KEY` (loaded from `.env` if present)
and is never passed on the command line.

### What a run prints

A header (db path, mode, season, endpoints, whether a key is present), one line
per competition/endpoint showing rows upserted, and the final `raw` row counts.
This makes a run self-verifying.

### Failure handling

Each competition/endpoint is wrapped so a single failure is reported and skipped
rather than aborting the whole run, but the process exits non-zero if anything
failed. That way it does as much as it can and still fails loudly for CI.

## Seasons currently loaded

- Live 2026/27 for all five leagues and the World Cup (default pull).
- Completed 2024/25 for the five leagues (backfilled, teams + matches only).

The 2024/25 backfill is what gives `fact_standings` finished results to work
from. CI only pulls the live season; it does not re-pull the frozen backfill,
which cannot change.
