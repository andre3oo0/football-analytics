# Contributing

Thanks for taking a look. This is a short onboarding guide for anyone who wants
to run the project or make a change. For the full detail, the [docs/](docs/)
folder has topic-by-topic reference material; start with
[docs/architecture.md](docs/architecture.md).

## What the project is

A small ELT pipeline: Python ingests football data from the football-data.org
API into a local DuckDB warehouse, and dbt models it into a tested star schema.
GitHub Actions runs it on a schedule. See the [README](README.md) for the
overview.

## Getting set up

You need Python 3.11+ and a free football-data.org API key
(https://www.football-data.org/client/register).

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env                 # then set FOOTBALL_DATA_API_KEY
```

Then build it:

```bash
python -m ingestion.run              # loads raw from cached JSON (no API calls)
cd dbt && dbt build --profiles-dir . # run models + tests
```

`dbt build` should end with `PASS=73, ERROR=0`. Full command reference and
troubleshooting are in [docs/running-the-project.md](docs/running-the-project.md).

### A couple of things that will confuse you otherwise

- `fact_standings` holds three seasons: the two completed backfills (2024/25,
  2025/26) with full matchday progressions, plus the live 2026/27 season, which
  is only a couple of matchdays in and so has far fewer rows. That's expected.
  See [docs/design-decisions.md](docs/design-decisions.md).
- The `status` test warns rather than fails. The source sometimes returns junk
  (a kickoff timestamp) in that field. A warning is normal; a `stage` failure
  would be real.
- DuckDB is single-writer. Don't run two things against the file at once, and
  don't leave it open in a GUI (DBeaver) while the pipeline runs, or steps will
  block.
- If you hit `CERTIFICATE_VERIFY_FAILED`, you're behind an SSL-inspecting proxy;
  `truststore` (already a dependency) handles it.

## Project layout

```
ingestion/   Python: fetch -> cache JSON -> load DuckDB raw schema
dbt/
  models/staging/       thin views, 1:1 with raw
  models/intermediate/  joins, dedup, business logic
  models/marts/         star schema (dims + facts)
  tests/                custom singular tests
  seeds/                competition reference data
.github/workflows/      the scheduled pipeline
docs/                   detailed documentation
```

## How to make a change

1. Branch off `main`.
2. Make the change and rebuild: `python -m ingestion.run` then
   `cd dbt && dbt build --profiles-dir .`. Everything must stay green.
3. If you add or change a model, add or update its tests and its description in
   the neighbouring `_*.yml`.
4. Open a PR describing what changed and why.

## Conventions

- Keep the layers separate. Staging is 1:1 with raw and only renames, casts and
  unpacks JSON. Joins, dedup and business logic go in intermediate or marts.
  Don't collapse layers.
- Every model gets a description; every primary key gets `unique` + `not_null`;
  every foreign key gets a `relationships` test.
- `accepted_values` lists use the values actually observed in the data, not the
  full API set, so they fail loudly when the data changes. If a legitimate new
  value appears, widen the list as a deliberate one-line change.
- Comments are plain sentences. No ASCII banner/divider comment blocks.
- Ingestion stays thin: land the raw payload keyed by its natural key and let
  dbt do the interpretation.

## Where the reasoning lives

Design decisions, with rationale and alternatives, are written up in
[docs/design-decisions.md](docs/design-decisions.md). If you're about to change
something load-bearing (the standings derivation, the single fact table, the
incremental strategy), read that first so you know why it is the way it is.

## Tests and CI

`dbt build` runs models and tests together and fails on any failing test. The
GitHub Actions workflow does the same on a schedule and on demand; a red job
means a data problem. Details in
[docs/testing-and-quality.md](docs/testing-and-quality.md) and
[docs/orchestration.md](docs/orchestration.md).
