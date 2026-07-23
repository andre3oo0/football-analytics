# Testing and quality

Data quality is enforced two ways: dbt tests (which fail the build) and source
freshness (which tells you how current the data is). `dbt build` runs every model
and its tests together and exits non-zero if any test fails, so a data problem is
loud rather than silent.

Current state: `dbt build` reports `PASS=73, ERROR=0`.

## Generic tests

Declared in the `_*.yml` files next to the models.

### Primary keys

`unique` and `not_null` on every primary key:

- `dim_competitions.competition_code`, `dim_teams.team_id`, `dim_seasons.season_id`
- `fact_matches.match_id`, `fact_standings.standing_key`
- the seed `seed_competitions.competition_code`

### Foreign keys

A `relationships` test on every foreign key, so every fact row must resolve to a
real dimension row:

- `fact_matches.competition_code` -> `dim_competitions.competition_code`
- `fact_matches.season_id` -> `dim_seasons.season_id`
- `fact_matches.home_team_id` -> `dim_teams.team_id`
- `fact_matches.away_team_id` -> `dim_teams.team_id`
- `fact_standings.competition_code` -> `dim_competitions.competition_code`
- `fact_standings.season_id` -> `dim_seasons.season_id`
- `fact_standings.team_id` -> `dim_teams.team_id`
- `dim_seasons.competition_code` -> `dim_competitions.competition_code`

### accepted_values

On the enum-like columns:

- `stg_matches.status`: `SCHEDULED`, `FINISHED`, `AWARDED`
- `stg_matches.stage`: `REGULAR_SEASON`, `GROUP_STAGE`, `LAST_32`, `LAST_16`, `QUARTER_FINALS`, `SEMI_FINALS`, `THIRD_PLACE`, `FINAL`
- `stg_matches.winner`: `HOME_TEAM`, `AWAY_TEAM`, `DRAW`
- `stg_matches.duration`: `REGULAR`, `EXTRA_TIME`, `PENALTY_SHOOTOUT`
- `stg_standings.standing_type`: `TOTAL`, `HOME`, `AWAY`
- `dim_competitions.competition_type` and the seed: `LEAGUE`, `TOURNAMENT`

The `status` and `stage` lists contain only the values actually observed in the
data, not the full documented API set. This is deliberate: a test that accepts
everything catches nothing. When a genuinely new value appears (for example live
in-play statuses like `TIMED` or `IN_PLAY` once the 2026/27 season starts) the
test fails, which is the signal to look, confirm it's real, and widen the list as
a one-line change with a git trail.

Generic-test arguments are nested under `arguments:`, which is the form dbt 1.10+
expects, so the build has no deprecation warnings.

## Singular tests

Bespoke SQL tests in `dbt/tests/`. Each returns the offending rows; the test
fails if any come back.

| Test | Checks |
|------|--------|
| `assert_scores_never_negative` | No negative full-time or half-time scores in `fact_matches`. |
| `assert_wc_knockout_has_winner` | A finished World Cup knockout match is never a draw or a null winner. Catches stage/score inconsistencies. |
| `assert_standings_played_equals_wdl` | In `fact_standings`, `played = won + drawn + lost`. |
| `assert_standings_points_consistent` | In `fact_standings`, `points = won*3 + drawn`. |
| `assert_standings_played_monotonic` | A team's cumulative `played` never decreases as matchday increases. |

The last three are internal-consistency checks on the derived standings; if the
derivation logic ever regresses, they catch it.

## Source freshness

Defined on the `raw` source in `_staging__sources.yml`, using `_loaded_at` with
`warn_after: 24h` and `error_after: 72h`. Run it with:

```bash
cd dbt && dbt source freshness --profiles-dir .
```

It measures how stale ingestion is, which is the signal the schedule cares about:
if the scheduled pipeline stops refreshing, freshness degrades and it is visible.

## Running tests

```bash
cd dbt
dbt build --profiles-dir .   # models + tests
dbt test  --profiles-dir .   # tests only
dbt test --select fact_standings --profiles-dir .   # tests for one model
```
