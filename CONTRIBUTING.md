# Contributing

How to run the project and make a change. The [README](README.md) has the
overview; [docs/](docs/README.md) has the reference material.

## Setup

Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt  # runtime deps plus pytest and ruff
```

You don't need an API key to build. The committed fixture season is enough:

```bash
python -m ingestion.run --cache-dir tests/fixtures/raw --season 2024 --competitions PL
cd dbt && dbt build --profiles-dir .
```

For live data, copy `.env.example` to `.env` and set `FOOTBALL_DATA_API_KEY`.
Once a key is set, cache-first mode fetches any response that isn't cached yet.
[docs/running-the-project.md](docs/running-the-project.md) has every command.

## Things worth knowing first

- DuckDB allows one writer. Don't run two commands against the warehouse at
  once, and close any GUI (DBeaver) holding the file open, or steps will block.
- The fixture season is Premier League 2024/25 only. The other four leagues and
  the live season need an API key.
- `fact_standings` is incremental. After changing its logic, rebuild it with
  `dbt build --profiles-dir . --select fact_standings+ --full-refresh`.

## Making a change

1. Branch off `main`.
2. Run the checks CI runs:

   ```bash
   ruff check .
   pytest
   python -m ingestion.run --cache-dir tests/fixtures/raw --season 2024 --competitions PL
   cd dbt && dbt build --profiles-dir .
   ```

3. A new or changed model gets a description, tests, and (for a mart) contract
   columns with `data_type` in the neighbouring `_*.yml`.
4. If you changed the DAG or a foreign key, regenerate the diagrams and commit
   the SVGs. CI fails if they are out of date.

   ```bash
   cd dbt && dbt parse --profiles-dir . && cd ..
   python docs/generate_diagrams.py
   ```

   The ER diagram's layout is curated in the script, and the script exits
   non-zero if the foreign keys it draws differ from the `relationships` tests.
5. Open a pull request saying what changed and why.

## Conventions

- Staging is 1:1 with raw and only renames, casts, unpacks JSON and normalises
  values. Joins, dedup and business logic go in intermediate or marts.
- Every primary key gets `unique` and `not_null`, every foreign key a
  `relationships` test, and every fact a grain test (`unique_combination` when
  the grain spans several columns).
- `accepted_values` lists hold the values seen in the data, and they fail the
  build on anything new. If a legitimate value appears, add it as a deliberate
  edit.
- Ingestion lands the raw payload by natural key and leaves interpretation to
  dbt.
- Comments are plain sentences.

Before changing the standings derivation, the incremental strategy or the
fact tables, read [docs/design-decisions.md](docs/design-decisions.md).
