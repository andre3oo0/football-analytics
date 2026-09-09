# Documentation

Detailed reference documentation for the football data pipeline. If you just
want the short overview, read the top-level [README](../README.md); if you're
getting started or contributing, read [CONTRIBUTING.md](../CONTRIBUTING.md).
These pages go deeper and are split by topic.

The Power BI report itself is out of scope for now. The Parquet serving layer
that would feed it is documented in [exports.md](exports.md).

## Contents

1. [Architecture](architecture.md) — the layers, data flow, warehouse and schemas.
2. [Running the project](running-the-project.md) — setup, every command, rebuilds, troubleshooting.
3. [Ingestion](ingestion.md) — the Python layer: rate limiting, caching, idempotent loads, CLI reference.
4. [Data model](data-model.md) — the dimensional model, the ERD, and how `fact_standings` is derived.
5. [Data dictionary](data-dictionary.md) — every table and column, with types.
6. [Testing and quality](testing-and-quality.md) — generic tests, singular tests, source freshness.
7. [Orchestration](orchestration.md) — the GitHub Actions workflow.
8. [Design decisions](design-decisions.md) — the decisions, with rationale and alternatives.
9. [Exports](exports.md) — the Parquet serving layer for BI tools.

The diagrams in this folder (`lineage_dag.svg`, `erd.svg`) are generated, not
screenshotted. Rebuild them with:

```bash
cd dbt && dbt parse --profiles-dir . && cd ..
python docs/generate_diagrams.py
```

## The one-paragraph version

Python pulls football data from football-data.org, caches each response to disk,
and upserts it into a DuckDB `raw` schema keyed by natural key so it is
idempotent. dbt then builds a tested, documented star schema on top: thin
staging views, intermediate views for logic, and mart tables (`dim_competitions`,
`dim_teams`, `dim_seasons`, `fact_matches`, `fact_standings`). `fact_standings`
is derived from finished match results rather than the API's standings snapshot.
GitHub Actions runs ingest then `dbt build` on a schedule and fails loudly if any
test fails. A small read-only script exports the marts to Parquet.
