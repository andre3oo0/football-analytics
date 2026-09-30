[![ci](https://github.com/andre3oo0/football-analytics/actions/workflows/ci.yml/badge.svg)](https://github.com/andre3oo0/football-analytics/actions/workflows/ci.yml)
[![football-data-pipeline](https://github.com/andre3oo0/football-analytics/actions/workflows/pipeline.yml/badge.svg)](https://github.com/andre3oo0/football-analytics/actions/workflows/pipeline.yml)

# Football data pipeline

A data-engineering portfolio project. Python pulls league data from the
football-data.org API into a DuckDB warehouse, dbt models it into a tested star
schema, and GitHub Actions runs it every night at 02:00 South African time
(started by an external cron service, since GitHub's own scheduler runs
hours late). The marts are exported to Parquet for a BI tool.

The work is in the ingestion guarantees, the dimensional model and the tests.
There is no dashboard in the repo yet (see [Known limitations](#known-limitations)).

## Architecture

```
football-data.org API (REST v4, free tier: 10 requests/minute)
   |  ingestion/ (Python): throttle, retry, validate, cache to data/raw/*.json
   v
DuckDB raw schema        key + untouched JSON payload; one transaction per run;
   |                     every run logged in raw._load_runs
   |  dbt
   v
staging (views)          rename, cast, unpack JSON
intermediate (views)     season dedup, match-level derivations
marts (tables)           7 tables with enforced contracts
   |
   v
export_marts.py -> exports/*.parquet
```

![dbt lineage](docs/lineage_dag.svg)

The lineage and the [ER diagram](docs/erd.svg) are generated from dbt's
manifest by `docs/generate_diagrams.py`. CI regenerates both and fails if the
committed SVGs differ.

## Data

Five leagues: Premier League (PL), La Liga (PD), Bundesliga (BL1), Serie A (SA)
and Ligue 1 (FL1). The list lives in
[`dbt/seeds/seed_competitions.csv`](dbt/seeds/seed_competitions.csv), which both
ingestion and `dim_competitions` read. The nightly pipeline holds the live
2026/27 season plus 2024/25 and 2025/26. Three endpoints per competition:
teams, matches and standings.

## The model

| Table | Grain |
|-------|-------|
| `dim_competitions` | competition |
| `dim_seasons` | competition-season |
| `dim_teams` | team (Type 1) |
| `dim_date` | calendar day covering every season and kickoff |
| `fact_matches` | match |
| `fct_team_matches` | team per match (two rows per match) |
| `fact_standings` | competition, season, team and matchday |

`fact_standings` is the league table after each matchday, derived from match
results. Each snapshot is taken as of a date, so a postponed game played weeks
later doesn't rewrite past tables. It is built incrementally, one season at a
time. The mechanism is in [docs/data-model.md](docs/data-model.md) and the
reasoning in [docs/design-decisions.md](docs/design-decisions.md).

## Quickstart

With no API key, using one committed season (Premier League 2024/25) in
`tests/fixtures/raw`:

```bash
python -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

python -m ingestion.run --cache-dir tests/fixtures/raw --season 2024 --competitions PL
cd dbt && dbt build --profiles-dir .
```

With a free football-data.org API key in `.env` (copy `.env.example`),
`python -m ingestion.run` pulls the live season for all five leagues and
`--season 2024` / `--season 2025` add the completed ones. See
[docs/running-the-project.md](docs/running-the-project.md).

## What is tested

- pytest covers the API client (retries, 404s, invalid bodies never cached),
  response validation, the loader (idempotency, change-only upserts, deletes,
  rollback) and a full ingestion run over the fixtures.
- dbt unit tests pin the standings logic on hand-built data: a postponed
  match, shared positions, and a team with no game in a snapshot window.
- dbt data tests check keys, every foreign key, enum values, the grain of
  each fact, and the business rules: a complete double round-robin, the API's
  winner agreeing with the score, and snapshots moving forward.
- Contracts on all seven marts fix the column names and types.
- The derived league table is reconciled against the standings endpoint for
  every season, team by team.

CI runs all of it on every pull request, with no API key. Details in
[docs/testing-and-quality.md](docs/testing-and-quality.md).

### AWARDED matches

football-data.org's standings table leaves out AWARDED matches, while the
leagues count them. The data holds three: Union Berlin 0-2 Bochum (Bundesliga
2024/25), Montpellier 0-2 Saint-Étienne (Ligue 1 2024/25) and Nantes 0-0
Toulouse (Ligue 1 2025/26). `fact_standings` counts them, as the leagues do,
and the reconciliation test subtracts their contribution before comparing with
the endpoint.

## Known limitations

- The date each matchday snapshot is taken at comes from a heuristic: the last
  game within 3 days of the round's median kickoff date.
- Teams level on points, goal difference and goals scored share a position.
  Head-to-head tie-breaks are not modelled.
- Points deductions are not modelled. The reconciliation test would fail if one
  happened.
- No history: `dim_teams` is Type 1 and raw keeps only the current payload.
- The nightly pipeline keeps its warehouse in the GitHub Actions cache, which
  GitHub evicts after 7 days without use. The next run re-pulls the completed
  seasons.
- The 02:00 start depends on an external cron service and a GitHub token that
  expires. If either fails, GitHub's own schedule runs the pipeline, hours late.
- Each run re-pulls whole seasons; there is no date-windowed extraction.
- DuckDB allows one writer, so steps run one after another.
- `kickoff_date` is the UTC date of kickoff.
- The Power BI model is not in the repo. That work is paused.

The fuller list, with consequences, is in
[docs/design-decisions.md](docs/design-decisions.md#known-limitations).

## Documentation

[docs/README.md](docs/README.md) indexes the reference docs: architecture,
running the project, ingestion, data model, data dictionary, testing,
orchestration, design decisions and exports.
[CONTRIBUTING.md](CONTRIBUTING.md) covers making a change.

## Repo layout

```
ingestion/            fetch, validate, cache, load the raw schema
dbt/
  models/staging/       thin views over raw
  models/intermediate/  season dedup, match-level derivations
  models/marts/         the star schema
  models/_unit_tests.yml
  tests/                singular tests and one generic test
  seeds/                the competitions in scope
tests/                pytest suite; fixtures/raw holds one real season
export_marts.py       marts -> Parquet
docs/                 reference docs and generated diagrams
.github/workflows/    ci.yml (pull requests) and pipeline.yml (nightly)
data/                 DuckDB file and cached JSON (git-ignored)
```
