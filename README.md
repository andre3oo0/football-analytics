# Football data pipeline

An end-to-end analytics engineering project. It pulls football data from a
public API, lands it raw in a local warehouse, and models it into a tested,
documented star schema with dbt, all wired up to run on a schedule in GitHub
Actions.

The interesting part here is the transformation, testing, documentation and
orchestration, not a dashboard at the end. The dimensional model, the dbt tests,
and the question "does this fail loudly when the data is wrong?" are the point.

## Documentation

Detailed reference docs live in [docs/](docs/README.md): architecture, running
the project, ingestion internals, the data model and dictionary, testing,
orchestration, and the design decisions. New here?
[CONTRIBUTING.md](CONTRIBUTING.md) is a short onboarding guide.

## Stack

- Python 3.11+ for ingestion only
- DuckDB as the warehouse (a single local `.duckdb` file)
- dbt-duckdb for all transformation, testing and docs
- GitHub Actions for scheduling

## How it fits together

```
football-data.org API (REST v4, free tier: 10 req/min)
        |
        |  Python ingestion: rate-limited (~8/min) + backoff, cache to disk first
        v
  data/raw/*.json           every response cached before loading
        |
        v
  DuckDB (raw schema)        idempotent upsert by natural key, no duplicates
        |
        |  dbt
        v
  staging/       1:1 with raw, rename + cast + unpack only (views)
  intermediate/  joins, dedup, business logic (views)
  marts/         star schema, dims + facts (tables)
        |
        v
  dbt tests (generic + singular)  +  dbt docs (lineage)
        |
        v
  GitHub Actions: cron + manual, ingest -> dbt build, red on any test failure
```

| Layer         | Tech           | What it does                                  |
|---------------|----------------|-----------------------------------------------|
| Ingestion     | Python 3.11+   | Fetch, cache raw JSON, load the `raw` schema  |
| Warehouse     | DuckDB         | One local `.duckdb` file                      |
| Staging       | dbt (views)    | Rename / cast / unpack only, stays thin       |
| Intermediate  | dbt (views)    | Joins, dedup, business logic                  |
| Marts         | dbt (tables)   | Star schema (dims + facts)                    |
| Orchestration | GitHub Actions | Scheduled + manual runs                       |

## Data source

[football-data.org](https://www.football-data.org/) REST API v4, free tier.

- Auth is an API key sent as the `X-Auth-Token` header, read from the
  `FOOTBALL_DATA_API_KEY` environment variable. It is never hardcoded or
  committed.
- The free tier allows 10 requests a minute, so the client throttles to about 8
  a minute and backs off on HTTP 429. Getting IP-banned isn't really possible.
- Every response is written to `data/raw/` as JSON before it's loaded, so
  re-running locally doesn't hit the API again.

Competitions:

| Code | Competition         | Type       |
|------|---------------------|------------|
| PL   | Premier League      | LEAGUE     |
| PD   | La Liga             | LEAGUE     |
| BL1  | Bundesliga          | LEAGUE     |
| SA   | Serie A             | LEAGUE     |
| FL1  | Ligue 1             | LEAGUE     |
| WC   | FIFA World Cup 2026 | TOURNAMENT |

Endpoints per competition: `/teams`, `/matches`, `/standings`.

Seasons: the five leagues are pulled for the live 2026/27 season, plus one
completed season (2024/25, via `--season 2024`). The completed season is what
gives `fact_standings` real finished results to work from. Ingestion is
season-aware and caches each season separately.

### About the off-season

Worth being upfront about: right now the leagues are in the 2026/27 off-season.
Every league fixture is scheduled with no result yet, so a table built from
finished matches is legitimately empty for the live season. That's exactly why I
also backfilled the completed 2024/25 season, which is where the standings
progression and the incremental behaviour are actually demonstrated. A scheduled
run tonight ingests the live season, builds everything and passes its tests, but
`fact_standings` stays empty until 2026/27 actually kicks off. The same pipeline
produces real standings from that point on with no code change.

## Dimensional model

- `dim_competitions`: one row per competition, with a `competition_type` of
  LEAGUE or TOURNAMENT.
- `dim_teams`: one row per team, unioned across the seasons ingested.
- `dim_seasons`: one row per competition-season.
- `fact_matches`: one row per match across every competition, leagues and the
  World Cup in the same table. A `stage` column separates REGULAR_SEASON from
  the World Cup rounds. Scores are nullable.
- `fact_standings`: one row per team per matchday, derived by cumulating
  finished match results (not the standings endpoint), built incrementally,
  leagues only.

Current row counts: `dim_competitions` 6, `dim_teams` 164, `dim_seasons` 11,
`fact_matches` 3,608, `fact_standings` 3,504.

## Design decisions

The whole reason to write these down is so I can defend each one.

**Idempotent ingestion means upsert by natural key, enforced by the table.**
Each raw table declares its natural key as a PRIMARY KEY (`team_id`, `match_id`,
and `(competition_code, season_id, team_id, matchday, standing_type)` for
standings). Loads run `INSERT ... ON CONFLICT DO UPDATE`, so re-running never
duplicates a row and a re-fetched match overwrites its old row. There's exactly
one current row per key; I don't keep raw history.

**Raw stores the key plus the untouched JSON payload, not flattened columns.**
That keeps ingestion generic and hard to break when the API adds a field, and it
pushes all the field-level work into dbt where it belongs. Staging then unpacks
the JSON, one thin view per source, no joins or logic.

**One `fact_matches` for both leagues and the World Cup.** The grain is the same
(a match is a match) and most questions cross competitions. Splitting into
separate fact tables would just force UNIONs. The `stage` column and the
competition FK carry the distinction instead.

**`fact_standings` is derived from match results, not the standings endpoint.**
The endpoint only returns one current table, and in the off-season it returns
last season's final numbers stamped with the new season at matchday 1, which is
self-contradictory. Computing each matchday's table from finished results is
consistent and gives a real week-by-week progression. As a sanity check, the
derived 2024/25 Premier League table matches reality (Liverpool champions on 84
points). The raw standings still land in `raw.standings`, but nothing depends on
them.

**A definitive result counts, not just FINISHED.** An AWARDED match (a forfeit
with an official scoreline) has a real result and has to count, otherwise a
league table comes out wrong. So the rule is `has_result = status in
('FINISHED', 'AWARDED')`.

**`fact_standings` uses delete+insert on a surrogate key.** The key is
`standing_key` = `competition|season|team|matchday`. delete+insert deletes the
target rows whose key is in the incoming batch and reinserts, so a re-fetched
matchday is replaced in place rather than duplicated, and a new matchday is
appended. When new results land for a season the whole season is re-derived,
because a corrected early result changes every later matchday's totals. append
would duplicate; merge would add per-column update SQL for no real benefit here.

**`dim_competitions` comes from a seed.** `competition_type` is my own
classification rather than an API field, and the competition list is small static
reference data, which is what seeds are for.

**Schema names are kept clean via a `generate_schema_name` macro.** dbt's default
would prefix everything (`main_staging`, ...). That default exists to stop
developers clobbering each other in a shared warehouse, which isn't a concern for
a single local file, so I override it for a more readable lineage graph.

**Everything runs single-writer.** DuckDB allows one writer at a time. Ingest and
each dbt command run as separate sequential processes that open and close the
file, and the CI job uses a concurrency group so two scheduled runs can't
overlap.

## Tests

- `unique` and `not_null` on every primary key.
- A `relationships` test on every foreign key (each fact FK back to its dim).
- `accepted_values` on the enum-like columns. `status` and `stage` list only the
  values actually seen in the data, so they fail if something unexpected shows
  up rather than quietly accepting it.
- Five singular tests: scores are never negative; a finished World Cup knockout
  is never a draw with a null winner; `played = won + drawn + lost`;
  `points = won*3 + drawn`; and cumulative games played never decreases as the
  matchday increases.

`dbt build` runs models and tests together and comes back with `PASS=73,
ERROR=0`.

## Local setup and run

```bash
# 1. Virtual environment (Python 3.11+)
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. Dependencies
pip install -r requirements.txt

# 3. Credentials
cp .env.example .env               # then paste your football-data.org key

# 4. Ingest
python -m ingestion.run                         # cache-first, no API calls if cached
# python -m ingestion.run --refresh             # re-fetch the live season
# one completed season for the derived standings:
# python -m ingestion.run --refresh --season 2024 --competitions PL PD BL1 SA FL1 --endpoints teams matches

# 5. Transform, test, docs (run from dbt/)
cd dbt
dbt build --profiles-dir .
dbt source freshness --profiles-dir .
dbt docs generate --profiles-dir . && dbt docs serve --profiles-dir .
```

## Orchestration

[`.github/workflows/pipeline.yml`](.github/workflows/pipeline.yml) runs on a cron
schedule (06:00 UTC) and on manual dispatch. The steps are sequential (install,
ingest the live season, `dbt build`, generate docs), each its own process so the
DuckDB file is never opened by two writers at once. `dbt build` exits non-zero if
any test fails, so a data problem turns the job red.

The API key comes from a GitHub repository secret, `FOOTBALL_DATA_API_KEY`,
injected as an environment variable. Only `.env.example` is in git.

On TLS: locally I'm behind an SSL-inspecting proxy, so the client uses
`truststore` to verify against the OS trust store (which has the corporate root)
instead of certifi's bundle. On a GitHub runner there's no corporate root, so the
OS store is just the normal public CAs and this becomes ordinary public-CA
verification. Verification stays on either way.

CI only pulls the live current season. I don't re-pull the frozen 2024/25
backfill on a schedule, because it can't change.

To run it on GitHub:

```bash
git remote add origin https://github.com/<you>/football-analytics.git
git push -u origin main
# Settings > Secrets and variables > Actions > New repository secret
#   FOOTBALL_DATA_API_KEY = <your key>
# Then: Actions > football-data-pipeline > Run workflow
```

## Lineage

The rendered dbt docs graph, sources and seed through to the marts, with the
singular tests hanging off the facts:

![dbt docs lineage graph](docs/lineage_dag.png)

Same thing as a diagram that renders inline on GitHub:

```mermaid
flowchart LR
  subgraph raw["raw sources"]
    rt[teams]; rm[matches]; rs[standings]
  end
  sc([seed_competitions])

  rt --> stg_teams
  rm --> stg_matches
  rs --> stg_standings

  stg_matches --> int_matches
  stg_matches --> int_seasons

  sc --> dim_competitions
  stg_teams --> dim_teams
  int_seasons --> dim_seasons
  int_matches --> fact_matches
  fact_matches --> fact_standings
  dim_competitions --> fact_standings

  classDef mart fill:#d5e8d4,stroke:#2d6a2d;
  class dim_competitions,dim_teams,dim_seasons,fact_matches,fact_standings mart;
```

## Repo layout

```
ingestion/          Python: fetch -> cache raw JSON -> load DuckDB raw schema
dbt/
  models/staging/       1:1 with raw, views
  models/intermediate/  joins, dedup, business logic
  models/marts/         star schema, tables
  tests/                custom singular tests
  seeds/                competition reference data
.github/workflows/  scheduled pipeline
data/               DuckDB file + cached raw JSON (git-ignored)
```
