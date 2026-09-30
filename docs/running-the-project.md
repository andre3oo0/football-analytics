# Running the project

Run ingestion, pytest, ruff and the scripts from the repo root, and dbt from
`dbt/` with `--profiles-dir .`.

## Setup

Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements-dev.lock   # exact versions CI uses; requirements.lock without pytest/ruff
```

For live data you need a free football-data.org key
(https://www.football-data.org/client/register):

```bash
cp .env.example .env                   # then set FOOTBALL_DATA_API_KEY
```

`.env` is git-ignored. Without a key, only cached responses can be loaded.

## Build without an API key

`tests/fixtures/raw` holds one real season, Premier League 2024/25 (teams,
matches and standings):

```bash
python -m ingestion.run --cache-dir tests/fixtures/raw --season 2024 --competitions PL
cd dbt && dbt build --profiles-dir .
```

This is what CI runs. If a key is set in `.env`, cache-first mode still fetches
any response that isn't cached, so keep to `--competitions PL --season 2024`
with the fixtures.

## Build with live data

```bash
python -m ingestion.run --season 2024    # 2024/25, all five leagues
python -m ingestion.run --season 2025    # 2025/26
python -m ingestion.run                  # the live season
cd dbt && dbt build --profiles-dir .
```

Each fetch is cached in `data/raw/`, so repeating these commands costs no API
calls. At the rate limit a full first pull (45 requests) takes about six
minutes.

To pick up new results for the live season:

```bash
python -m ingestion.run --refresh
cd dbt && dbt build --profiles-dir .
```

The full ingestion CLI is in [ingestion.md](ingestion.md).

To change a dependency, edit the range in `requirements.txt` or
`requirements-dev.txt` and regenerate the lock files
([uv](https://docs.astral.sh/uv/) is needed for this step only):

```bash
uv pip compile requirements.txt --universal --python-version 3.11 -o requirements.lock
uv pip compile requirements-dev.txt --universal --python-version 3.11 -o requirements-dev.lock
```

## Commands

```bash
# Python
pytest                                   # unit and integration tests
ruff check .                             # lint

# dbt (from dbt/)
dbt build --profiles-dir .               # seed, models, unit tests, data tests
dbt build --profiles-dir . --full-refresh
dbt test  --profiles-dir . --select fact_standings
dbt source freshness --profiles-dir .    # age of the last successful ingestion run
dbt docs generate --profiles-dir . && dbt docs serve --profiles-dir .   # or read them at https://andre3oo0.github.io/football-analytics/

# from the repo root
python export_marts.py                   # marts -> exports/*.parquet
cd dbt && dbt parse --profiles-dir . && cd .. && python docs/generate_diagrams.py
```

## Rebuild the warehouse from scratch

The DuckDB file is disposable. With the JSON cache in place this needs no API
calls:

```bash
rm -f data/football.duckdb data/football.duckdb.wal
python -m ingestion.run --season 2024
python -m ingestion.run --season 2025
python -m ingestion.run
cd dbt && dbt build --profiles-dir .
```

## Checking what's loaded

Row counts change with every run, so they aren't written down here. The
ingestion run prints the raw counts at the end, `export_marts.py` prints each
mart's count, and the run log shows what each run did:

```bash
python -c "import duckdb; duckdb.connect('data/football.duckdb', read_only=True).sql('select * from raw._load_runs order by finished_at desc limit 5').show()"
```

## Troubleshooting

| Symptom | Cause and fix |
|---------|---------------|
| `No cached response ... and no API key set` | The response isn't cached and there is no key. Set `FOOTBALL_DATA_API_KEY`, or use `--cache-dir tests/fixtures/raw --season 2024 --competitions PL`. |
| Ingestion exits 1 | An endpoint failed and the run rolled back. The log and `raw._load_runs.failures` say which. Re-run; successful responses are cached. |
| `InvalidResponse` | The API returned 200 with an unexpected body. Nothing was cached. Re-run with `--refresh` later; if it persists, the API changed shape. |
| A lock error or a step that hangs | Another process holds the DuckDB file (another run, DBeaver). Close it. |
| `CERTIFICATE_VERIFY_FAILED` | Your network's root CA isn't trusted. Install `truststore` (in `requirements.txt`) and make sure the CA is in the OS trust store. |
| A historical season returns 403 | The free tier doesn't expose that season. |
| dbt: `Database "football" does not exist` | The source expects the catalog `football`, i.e. a file named `football.duckdb`. |
| dbt can't find the profile | Run from `dbt/` with `--profiles-dir .`. |
| `accepted_values` fails on `status` or `stage` | The API returned a value not seen before. Check it's legitimate and add it in `dbt/models/staging/_staging__models.yml`. |
| `fact_standings` looks stale after a logic change | It's incremental. Run `dbt build --profiles-dir . --select fact_standings+ --full-refresh`. |
