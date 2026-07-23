# Running the project

Setup, every command you'll need, common workflows, and troubleshooting.

## Prerequisites

- Python 3.11 or newer (developed on 3.13).
- A free football-data.org API key: https://www.football-data.org/client/register
- Git.

Pinned dependency versions live in [requirements.txt](../requirements.txt):
`requests`, `python-dotenv`, `duckdb`, `truststore` for ingestion, and
`dbt-duckdb` (which pulls in dbt-core) for transformation. The local build runs
Python 3.13, DuckDB 1.5.x, dbt-core 1.12 with the dbt-duckdb adapter 1.10.x.

## First-time setup

```bash
# 1. Virtual environment
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate

# 2. Dependencies
pip install -r requirements.txt

# 3. Credentials
cp .env.example .env
# then edit .env and set FOOTBALL_DATA_API_KEY=your_key_here
```

`.env` is git-ignored and holds the only secret. In CI the same variable comes
from a GitHub Actions repository secret. Only `.env.example` is committed.

### Corporate proxy / TLS

If your network does SSL inspection (a corporate root CA), plain certificate
verification will fail with `CERTIFICATE_VERIFY_FAILED`. The client handles this
by calling `truststore.inject_into_ssl()`, which verifies against the operating
system trust store (where that root lives) instead of certifi's bundle.
Verification stays on. On a normal network or a CI runner there is no corporate
root, so truststore simply uses the public CAs and nothing special happens.

## Everyday commands

Run ingestion from the repo root, and dbt from the `dbt/` directory.

### Ingest

```bash
# cache-first: rebuild raw from cached JSON, zero API calls
python -m ingestion.run

# re-fetch the live current season from the API
python -m ingestion.run --refresh

# backfill one completed league season (teams + matches only)
python -m ingestion.run --refresh --season 2024 \
    --competitions PL PD BL1 SA FL1 --endpoints teams matches
```

Full flag reference is in [ingestion.md](ingestion.md).

### Transform, test, docs

```bash
cd dbt
dbt build --profiles-dir .              # run models + tests in one pass
dbt run   --profiles-dir .              # models only
dbt test  --profiles-dir .              # tests only
dbt source freshness --profiles-dir .   # how stale ingestion is
dbt docs generate --profiles-dir .      # build catalog + manifest
dbt docs serve   --profiles-dir .       # interactive docs at localhost:8080
```

Always pass `--profiles-dir .` and run from `dbt/`; the committed `profiles.yml`
lives there and the DuckDB path is resolved relative to the working directory.

### Export to Parquet

```bash
python export_marts.py                  # writes exports/*.parquet, read-only
```

## Common workflows

### Rebuild the warehouse from scratch

The DuckDB file is disposable. To rebuild it from cached JSON (no API calls):

```bash
rm -f data/football.duckdb data/football.duckdb.wal
python -m ingestion.run                                                   # live season from cache
python -m ingestion.run --season 2024 --competitions PL PD BL1 SA FL1 --endpoints teams matches
python -m ingestion.run --season 2025 --competitions PL PD BL1 SA FL1 --endpoints teams matches
cd dbt && dbt build --full-refresh --profiles-dir .
```

### Add a completed season for standings

```bash
python -m ingestion.run --refresh --season <year> \
    --competitions PL PD BL1 SA FL1 --endpoints teams matches
cd dbt && dbt build --profiles-dir .
```

### Refresh live data

```bash
python -m ingestion.run --refresh
cd dbt && dbt build --profiles-dir .
```

## Expected results

After a full build against the current data:

| Table             | Rows  |
|-------------------|-------|
| dim_competitions  | 6     |
| dim_teams         | 169   |
| dim_seasons       | 16    |
| fact_matches      | 5,360 |
| fact_standings    | 7,008 |

`dbt build` should report `PASS=73, ERROR=0`. `fact_standings` is populated from
the 2024/25 and 2025/26 backfills (3,504 rows each); it stays empty for the live
2026/27 season until matches are actually played (see
[design-decisions.md](design-decisions.md)).

## Troubleshooting

| Symptom | Cause and fix |
|---------|---------------|
| `CERTIFICATE_VERIFY_FAILED` | SSL-inspecting proxy. Make sure `truststore` is installed; the client injects it automatically. |
| A run hangs or a lock error | Something else holds the DuckDB file open for writing (another run, DBeaver). Close it; keep steps sequential. |
| `fact_standings` is empty | Expected if only the live off-season data is loaded. Backfill a completed season (2024/25 or 2025/26). |
| dbt: `Database "football" does not exist` | The DuckDB file stem must be `football` (the source `database:` is set to that). Keep the filename or update `_staging__sources.yml`. |
| dbt can't find the profile | Run from `dbt/` with `--profiles-dir .`. |
| A historical season 403s | The free tier does not expose that season. |
| `accepted_values` test fails on `status`/`stage` | The data produced a new value (for example live in-play statuses once the season starts). Confirm it's legitimate, then widen the list in `_staging__models.yml`. This is the intended fail-loud behaviour. |
