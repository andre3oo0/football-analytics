# ⚽ Football Data Pipeline — Analytics Engineering Portfolio

An end-to-end **analytics engineering** project: ingest football data from a
public REST API, land it raw in a local warehouse, and model it into a tested,
documented star schema with dbt — orchestrated on a schedule via GitHub Actions.

The point of this project is the **transformation, testing, documentation, and
orchestration layers**, not the final report. The dimensional model, the dbt
tests, and the "does it fail loudly?" question are the deliverable.

> **Status:** 🚧 Under construction — being built in phases. See
> [Build phases](#build-phases) for what is done and what is next.

---

## Architecture

```
football-data.org API (REST v4, free tier: 10 req/min)
        │
        │  Python ingestion  ─ rate-limited (~8 req/min) + exponential backoff
        ▼
  data/raw/*.json           ─ every response cached to disk BEFORE loading
        │                      (dev re-runs never re-hit the API)
        ▼
  DuckDB  ── raw schema      ─ idempotent load, no duplicates
        │
        │  dbt-duckdb
        ▼
  staging/       ─ 1:1 with raw; rename + cast only; materialized as views
  intermediate/  ─ joins, dedup, business logic
  marts/         ─ star schema; materialized as tables
        │
        ▼
  dbt tests (generic + singular)  +  dbt docs (lineage DAG)
        │
        ▼
  GitHub Actions ─ cron + manual; ingest → dbt run → dbt test; fails loudly
```

### Data flow layers

| Layer          | Tech           | Responsibility                                        |
|----------------|----------------|-------------------------------------------------------|
| Ingestion      | Python 3.11+   | Fetch, cache raw JSON, load DuckDB `raw` schema       |
| Warehouse      | DuckDB         | Single local `.duckdb` file                           |
| Staging        | dbt (views)    | Rename / cast only — stays thin                       |
| Intermediate   | dbt (views)    | Joins, dedup, business logic                          |
| Marts          | dbt (tables)   | Star schema (dims + facts)                            |
| Orchestration  | GitHub Actions | Scheduled + manual pipeline runs                      |

---

## Data source

[football-data.org](https://www.football-data.org/) REST API v4 (free tier).

- **Auth:** API key sent as the `X-Auth-Token` header, read from the
  `FOOTBALL_DATA_API_KEY` environment variable. Never hardcoded or committed.
- **Rate limit:** free tier allows **10 requests/minute**. We throttle to
  ~8 req/min with exponential backoff on HTTP 429 — an IP ban is impossible by
  design.
- **Caching:** every raw response is written to `data/raw/` as JSON *before*
  loading, so development re-runs do not re-hit the API.

### Competitions

| Code  | Competition            | Type       | Role in the project                       |
|-------|------------------------|------------|-------------------------------------------|
| PL    | Premier League         | LEAGUE     | Drives incremental + orchestration story  |
| PD    | La Liga                | LEAGUE     | ″                                         |
| BL1   | Bundesliga             | LEAGUE     | ″                                         |
| SA    | Serie A                | LEAGUE     | ″                                         |
| FL1   | Ligue 1                | LEAGUE     | ″                                         |
| WC    | FIFA World Cup 2026    | TOURNAMENT | Report headline; static, has knockout stages |

Endpoints per competition: `/competitions/{id}/teams`,
`/competitions/{id}/matches`, `/competitions/{id}/standings`.

---

## Dimensional model (target grain)

- **dim_competitions** — one row per competition (with a `competition_type`
  attribute: `LEAGUE` vs `TOURNAMENT`).
- **dim_teams** — one row per team.
- **dim_seasons** — one row per competition-season.
- **fact_matches** — **one row per match across ALL competitions** (leagues and
  World Cup share a single fact table). Includes a `stage` column
  (`REGULAR_SEASON` for leagues; `GROUP_STAGE` / `LAST_16` / `QUARTER_FINALS` /
  `SEMI_FINALS` / `FINAL` etc. for the WC). Scores are nullable.
- **fact_standings** — one row per team per matchday snapshot; built
  **incrementally**; driven by the live leagues, not the WC.

> Design rationale (why this grain, why one fact table for both leagues and the
> WC, why these tests) is written up in [Decisions](#decisions) below.

---

## Decisions

<!-- Each phase appends the decisions it made here, with the tradeoff and the
     choice, so every design choice is defensible in an interview. -->

### Phase 1 — scaffold

- **The repo lives in its own folder (`football-analytics/`), not directly on
  the Desktop.** `git init` should never wrap the entire Desktop. This is the
  repo root referred to as `/` throughout the spec.
- **Dependencies are pinned in a single `requirements.txt`** (ingestion + dbt
  together) rather than split files or a `pyproject.toml`. Tradeoff: a
  `pyproject.toml` reads as more "modern packaging," but this project ships no
  installable package — it is scripts + a dbt project. One commented
  `requirements.txt` is the most readable, works with both `venv` and `uv`, and
  keeps the CI install a one-liner.
- **Raw JSON cache lives in `data/raw/`; the folder is tracked but its contents
  are git-ignored** (`data/raw/*` + `!data/raw/.gitkeep`). This keeps the
  directory structure visible in the repo without ever committing pulled data.
- **The DuckDB file is a build artifact** (`*.duckdb` ignored) — the warehouse
  is always rebuildable from raw JSON + dbt, so it never belongs in git.

<!-- Later phases: why incremental fact_standings, why singular tests chosen,
     what a pipeline failure looks like, etc. -->

---

## Local setup & run

> Full run instructions are filled in as each phase lands. Skeleton below.

```bash
# 1. Create and activate a virtual environment (Python 3.11+)
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure credentials
cp .env.example .env             # then paste your football-data.org key

# 4. Ingest raw data           (Phase 2)
# python -m ingestion.run

# 5. Transform + test          (Phases 3–5)
# cd dbt && dbt run && dbt test

# 6. Generate docs / lineage   (Phase 5)
# cd dbt && dbt docs generate && dbt docs serve
```

---

## Build phases

- [x] **Phase 1** — repo scaffold (folders, `.gitignore`, `.env.example`,
      dependencies, README skeleton, git init + first commit)
- [ ] **Phase 2** — ingestion (fetch + JSON cache + rate limit + backoff +
      idempotent load into DuckDB `raw` schema)
- [ ] **Phase 3** — dbt project init + staging models + sources
- [ ] **Phase 4** — intermediate + marts (star schema, incremental
      `fact_standings`)
- [ ] **Phase 5** — tests (generic + singular) + descriptions + `dbt docs`
- [ ] **Phase 6** — GitHub Actions orchestration + final README pass

---

## Pipeline lineage (DAG)

<!-- Phase 5: paste the `dbt docs` lineage graph screenshot here. -->

_DAG screenshot goes here once the dbt models exist._
