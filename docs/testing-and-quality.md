# Testing and quality

Six layers, from the Python code to the published marts. `dbt build` runs the
unit tests, data tests and models together and exits non-zero on any failure;
CI runs every layer on each pull request.

## 1. pytest

`tests/` covers the ingestion package without network access. The API client
is given a fake session; the loader and the full run use a temporary DuckDB
file and the committed fixture season.

| File | Covers |
|------|--------|
| `test_api_client.py` | 200s cached, cache hits make no request, no key and no cache fails, 429 with and without `Retry-After`, 5xx then 200, connection errors and timeouts retried, retries bounded, 404 raises `ResourceNotFound`, other 4xx not retried, an invalid body is rejected and not cached, an invalid cached file is rejected |
| `test_validation.py` | the real fixtures pass; a matches body that is missing, null, empty, miscounted or has a match without an id fails; so do a miscounted teams body and standings without `season.id` |
| `test_loader.py` | first load inserts everything; a reload is idempotent and keeps `_loaded_at`; a changed payload is rewritten and restamped; a match missing from the response is deleted; standings explode to one row per team per type; rows without a key are skipped; rollback discards the run |
| `test_run.py` | a run over the fixtures loads and writes `raw._load_runs`, and a second run changes nothing; one bad file rolls back every endpoint; an unknown competition exits 2 |

```bash
pytest
ruff check .
```

`tests/fixtures/raw` holds real, minified responses for Premier League 2024/25.
The same files let anyone run the dbt build without an API key.

## 2. dbt unit tests

`dbt/models/_unit_tests.yml` runs models on hand-built inputs:

- **`fact_standings_postponed_match_and_ties`**: six teams over three matchdays.
  A matchday 2 game is played after matchday 3; the matchday 2 snapshot doesn't
  include it and the postponed game first counts in the latest snapshot. It also
  checks that a team with no game in a window still gets a row, and that teams
  level on points, goal difference and goals scored share a position.
- **`int_matches_awarded_counts_postponed_does_not`**: AWARDED has a result and
  points; POSTPONED and SCHEDULED do not, and neither do IN_PLAY or SUSPENDED
  matches that already carry a score and a provisional winner.
- **`stg_matches_normalises_timestamp_status`**: a kickoff timestamp in
  `status` becomes `SCHEDULED`, with the original kept in `status_raw`.

## 3. Generic data tests

Declared in the `_*.yml` files next to the models:

- `unique` and `not_null` on every primary key, including the seed.
- A `relationships` test on every foreign key: every fact to each of its
  dimensions (including `dim_date`), `fct_team_matches` to `fact_matches`, and
  `dim_seasons` to `dim_competitions`.
- `unique_combination`, a local generic test in `dbt/tests/generic/`, on the
  grain of `fct_team_matches` (match, team) and `fact_standings` (competition,
  season, team, matchday).
- `accepted_values` on `status`, `stage`, `winner`, `duration`, `standing_type`
  and `fct_team_matches.result`. The lists hold the values seen in the data and
  fail the build on anything new. `stage` accepts only `REGULAR_SEASON`.

## 4. Singular tests

SQL in `dbt/tests/`; each returns offending rows and fails if there are any.

| Test | Catches |
|------|---------|
| `assert_scores_never_negative` | a negative full-time or half-time score |
| `assert_results_have_scores` | a FINISHED or AWARDED match with a missing score or winner, e.g. after the API renames a score field and the staging cast produces nulls |
| `assert_winner_matches_score` | the API's `winner` disagreeing with the full-time score in a match decided in normal time |
| `assert_season_fixtures_complete` | missing or duplicated fixtures: a league of n teams must have n(n-1) fixtures, n-1 home and n-1 away per team, and 2(n-1) matchdays of n/2 fixtures |
| `assert_season_attributes_consistent` | a season whose matches disagree on its start or end date, which `int_seasons` relies on |
| `assert_standings_points_consistent` | `points <> 3 * won + drawn` at any snapshot. Points come from `winner` and W/D from the scores, so this compares two fields; it would also catch a points deduction |
| `assert_standings_snapshots_move_forward` | an `as_of_date` or a team's `played` going backwards as the matchday rises |
| `assert_standings_reconcile_with_endpoint` | the derived table disagreeing with the standings endpoint |

### The reconciliation test

For every season that has rows in `fact_standings` and in the endpoint, the
test compares the latest derived snapshot with the latest TOTAL snapshot from
the endpoint, team by team, on played, points, goal difference and goals
scored. A team present on only one side also fails.

The endpoint leaves AWARDED matches out of its table, while the leagues count
them. There are three in the data: Union Berlin 0-2 Bochum (Bundesliga
2024/25), Montpellier 0-2 Saint-Étienne (Ligue 1 2024/25) and Nantes 0-0
Toulouse (Ligue 1 2025/26). The test subtracts each team's AWARDED results
before comparing. Any other difference fails: a missed or double-counted result,
a wrong snapshot date for the latest matchday, a points deduction.

It assumes matches and standings come from the same ingestion run, which is the
default.

## 5. Contracts

All seven marts have `contract: {enforced: true}` with a `data_type` for every
column. dbt checks the model's output against the declared columns and types
before building it and fails on any mismatch, so a column rename or type change
in a mart has to be an explicit edit in `_marts__models.yml`.

## 6. Source freshness

Freshness is defined on `raw._load_runs`, using `finished_at` for successful
runs: warn after 26 hours, error after 72. It measures whether ingestion is
running. `_loaded_at` on the data tables only moves when content changes, so it
would warn during an international break.

```bash
cd dbt && dbt source freshness --profiles-dir .
```

Neither workflow runs this; it is a manual check.

## What isn't tested

- The live API itself. pytest uses a fake session and CI uses fixtures, so an
  API change surfaces first in the nightly pipeline, through validation or
  the data tests.
- Only one season of fixtures runs in CI. The other leagues and seasons are
  tested by the nightly pipeline's `dbt build`.
- `dim_date` and `dim_teams` attributes beyond their keys.
- Head-to-head ordering and points deductions, which aren't modelled.
- `export_marts.py` and `docs/generate_diagrams.py` have no unit tests. The
  pipeline runs the export daily and CI runs the diagram script.
- No test compares an incremental build with a full refresh. CI's second
  build runs the incremental branch, and the same data tests check its output.
