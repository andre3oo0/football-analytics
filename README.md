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

### Phase 2 — ingestion

- **Raw = the natural key + the untouched payload as JSON**, not a flattened
  set of typed columns. Tradeoff: flattening in Python would make ingestion
  brittle to any API field change and would smear interpretation into the EL
  step. Landing the raw JSON keyed by its natural key keeps ingestion generic
  ("land it, don't read it") and pushes *all* field-level rename/cast into dbt
  staging — which is exactly where the spec wants that logic to live.
- **Idempotency is enforced by a table PRIMARY KEY, not by convention.** Each
  raw table declares its natural key as a PK; loads use
  `INSERT ... ON CONFLICT (<pk>) DO UPDATE`. A duplicate can therefore never
  exist even if the loader is called wrongly — the database rejects it.
    - `raw.teams` PK `(team_id)`
    - `raw.matches` PK `(match_id)`
    - `raw.standings` PK `(competition_code, season_id, team_id, matchday)`
- **One current row per match — no raw SCD.** A re-fetched match that moved
  `SCHEDULED → FINISHED` overwrites its row. Point-in-time history lives only
  in `fact_standings` downstream, which is why `matchday` is part of the
  standings key: a new matchday is a new snapshot, not a new version of an
  existing row.
- **Standings: raw preserves EVERY table type the source returns.** The API's
  standings response can carry TOTAL and (mid-season) HOME/AWAY tables; raw
  lands all of them, so `standing_type` is part of the key
  `(competition_code, season_id, team_id, matchday, standing_type)`. Filtering
  to TOTAL is a *transformation* decision and is made explicitly downstream in
  `stg_standings`, not silently at ingest — dropping data to fit a schema is
  data loss in the wrong layer. (Note: for these competitions / the current
  pre-season the API returns only TOTAL, verified against the live endpoint;
  raw therefore contains only TOTAL today, but the loader no longer discards
  anything, so HOME/AWAY are captured automatically if/when the source
  provides them.) `currentMatchday` can be null pre-kickoff → coalesced to `0`
  (the PK column is `NOT NULL`).
- **Cache-first by default; `--refresh` to hit the API.** Every response is
  written to `data/raw/` *before* loading. Re-runs cost zero API calls unless
  `--refresh` is passed, so development never risks the rate limit.
- **Rate limiting is defensive by design:** ~8 req/min (7.5s min gap between
  real calls) against a 10/min hard cap, plus exponential backoff honouring
  `Retry-After` on HTTP 429. An IP ban is impossible.
- **TLS verification via the OS trust store (`truststore`).** The dev network
  does SSL inspection (a corporate root CA). Rather than the insecure
  `verify=False`, we verify against the OS store where that root is trusted —
  a no-op on normal networks. Verification stays ON everywhere.
- **The run fails loudly but finishes what it can:** a single unavailable
  endpoint is reported and skipped, and the process exits non-zero if anything
  failed.

### Phase 3 — dbt project, staging & sources

- **Sources point at the `raw` schema with freshness + descriptions.** Freshness
  is measured on `_loaded_at` (warn 24h / error 72h) — it answers "did the
  scheduled pipeline actually refresh the live leagues recently?", which is the
  orchestration signal Phase 6 depends on.
- **Staging is strictly 1:1 with raw: unpack JSON, rename, cast — nothing
  else.** Row counts match raw exactly (144 / 1856 / 144). No joins, no dedup,
  no filtering. This is enforced by reading, not asserted — the models contain
  only `source -> select` with column expressions.
- **The TOTAL-vs-HOME/AWAY decision is surfaced, not enforced, in staging.**
  `stg_standings` keeps every row and adds a documented `is_total_standing`
  flag. The actual filter (`where is_total_standing`) lands in the intermediate
  layer in Phase 4 — so the choice is explicit and testable, and staging never
  drops a row it received from raw.
- **`profiles.yml` is committed** (it holds only the DuckDB file path, no
  secrets) so the project is reproducible. dbt is run from `dbt/` with
  `--profiles-dir .`.
- **A `generate_schema_name` macro** gives clean schema names
  (`staging` / `intermediate` / `marts`) instead of dbt's default
  `main_staging` concatenation. The default guards against devs clobbering each
  other in a shared warehouse; that risk does not exist in a single local
  DuckDB file, so the cleaner names win for a readable lineage DAG.

### Phase 4 — intermediate & marts (the star schema)

- **One `fact_matches` for leagues AND the World Cup.** The grain is identical
  (a match is a match) and the interesting questions are cross-competition
  ("goals per matchday", "results by stage"). Splitting by competition would
  fragment that grain and force UNIONs for any cross-competition answer. The
  `stage` column + the competition FK carry the league/tournament distinction
  instead. Scores/measures are nullable and never fabricated to 0.
- **The TOTAL filter lives in `int_standings_total`** — a single documented
  `where is_total_standing`. Raw preserves all types, staging flags them, the
  intermediate layer makes the exclusion; it is auditable in one place.
- **`dim_competitions` comes from a seed**, because `competition_type`
  (LEAGUE vs TOURNAMENT) is our analytical classification, not a source field,
  and the list is small static reference data — the canonical use of a dbt
  seed. **`dim_seasons` is derived from the match payload's season object**
  (real source attributes: dates, current matchday); `season_id` is unique per
  competition, so it is the PK. **`dim_teams`** is straight from `stg_teams`,
  already unique on `team_id`.
- **`fact_standings` is incremental. This is the reasoned centrepiece:**
  - **`unique_key = standing_key`** (`competition|season|team|matchday`).
  - **`incremental_strategy = delete+insert`.** `append` would duplicate a
    re-fetched matchday; `delete+insert` deletes every target row whose
    `standing_key` is in the incoming batch then inserts the batch, so a
    re-fetched in-progress matchday is **replaced in place** while a brand-new
    matchday is inserted. `merge` would also work but adds per-column update SQL
    for no benefit on a single surrogate key.
  - **Watermark:** later runs only pull rows with `_loaded_at` newer than the
    max already stored. Every raw upsert bumps `_loaded_at`, so a re-fetched
    matchday is always picked up.
  - **First run vs later runs:** the first run (or `--full-refresh`) has no
    table yet, so `is_incremental()` is false and the whole history builds;
    later runs apply the watermark filter and delete+insert.
  - **Proven:** mutated one raw snapshot's points `85 → 999`, ran incrementally
    → the `(team, matchday)` row updated in place, `rows_for_key = 1` (no
    duplicate), `total = 144` unchanged; restored → back to `85`.
- **Single-writer discipline:** every step (ingest, each `dbt` invocation, each
  ad-hoc query) is its own process that opens and closes the DuckDB file before
  the next starts. DuckDB allows only one writer; two processes opening the file
  at once is what made a finished job look "hung" earlier. Phase 6 CI keeps the
  same strictly-sequential shape.

<!-- Later phases: why singular tests chosen, what a pipeline failure looks
     like, etc. -->

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
python -m ingestion.run              # cache-first: no API calls if already cached
# python -m ingestion.run --refresh  # re-fetch live data from the API
# python -m ingestion.run --competitions PL SA   # subset

# 5. Transform + test          (Phase 3+; run from the dbt/ dir)
cd dbt
dbt build --profiles-dir .           # run models + tests together
dbt source freshness --profiles-dir . # check ingestion recency
cd ..

# 6. Generate docs / lineage   (Phase 5)
# cd dbt && dbt docs generate --profiles-dir . && dbt docs serve --profiles-dir .
```

---

## Build phases

- [x] **Phase 1** — repo scaffold (folders, `.gitignore`, `.env.example`,
      dependencies, README skeleton, git init + first commit)
- [x] **Phase 2** — ingestion (fetch + JSON cache + rate limit + backoff +
      idempotent upsert-by-natural-key into DuckDB `raw` schema)
- [x] **Phase 3** — dbt project init + staging models + sources (freshness,
      descriptions, 1:1 typed views)
- [x] **Phase 4** — intermediate + marts (star schema, incremental
      `fact_standings` with delete+insert)
- [ ] **Phase 5** — tests (generic + singular) + descriptions + `dbt docs`
- [ ] **Phase 6** — GitHub Actions orchestration + final README pass

---

## Pipeline lineage (DAG)

<!-- Phase 5: paste the `dbt docs` lineage graph screenshot here. -->

_DAG screenshot goes here once the dbt models exist._
