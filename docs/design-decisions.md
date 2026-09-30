# Design decisions

Each decision is explained once, here. The other docs describe the mechanism
and link back.

## Ingestion

### Raw holds the key plus the untouched payload

Each raw row is the typed natural key, the API object as `json`, and two
metadata columns. Ingestion doesn't need to change when the API adds a field,
and every field-level decision is made in dbt, where it is tested. Flattening in
Python would couple ingestion to the API schema and split interpretation across
two languages.

### Idempotency comes from the primary key

The natural key is a `PRIMARY KEY` on each raw table and loads use
`INSERT ... ON CONFLICT DO UPDATE`, so a duplicate can't exist even if the
loader is called twice with the same data. Append-and-dedup-later would leave
duplicates in raw between runs; truncate-and-reload would lose the change
tracking below.

### Only changed rows are rewritten

The loader drops incoming rows whose payload matches the stored one before
upserting. `_loaded_at` then records when a row's content last changed, which
makes it a usable incremental watermark: an unchanged season doesn't trigger a
rebuild of `fact_standings`. The cost is one payload comparison per row, which
is negligible at this size.

The comparison ignores `lastUpdated` and the season's `currentMatchday`, which
the API rewrites on every match even when the match itself hasn't changed.
Without that, `rows_changed` would count a whole season every time a round
advanced.

### Removed matches are deleted; teams are not

A matches response is the complete fixture list for a season, so a match that
disappears from it was removed upstream and is deleted from raw. Teams stay: a
relegated team no longer appears in the current season's teams response, but
its earlier matches still reference it.

### A run is one transaction

If any endpoint fails, the whole run rolls back. A partial load would give
dbt matches from today and standings from yesterday, which the reconciliation
test compares directly. Retrying is cheap because successful responses are
already cached, so all-or-nothing costs little.

### Responses are validated before they are cached

A 200 with an unexpected body (an empty list, a count that doesn't match, a
missing id) would otherwise load zero rows, report success, and then be served
from the cache on every later run. Validating before the write, writing
atomically, and validating again on read means a bad file is never trusted.

### Large deletes are refused

A matches response that would remove more than five stored matches of a season
is treated as a bad response. The run fails and raw keeps its data. Genuine
removals of that size don't happen in a league season, while a truncated or
filtered response from the API would otherwise wipe matches silently.

### Every run is logged in raw._load_runs

The log holds status, counts and failures per run. It is what source freshness
is measured on (see below), and it is where to look first when a pipeline run
fails.

### Timestamps are naive UTC

`_loaded_at` and the run log use UTC without a time zone, so a laptop and a CI
runner write comparable values. `kickoff_date` is also the UTC date.

### Competitions come from one seed

`seed_competitions.csv` lists the competitions in scope. Ingestion reads it to
decide what to pull and dbt builds `dim_competitions` from it, so the two can't
disagree about which leagues exist.

### TLS verifies against the OS trust store

`truststore` points TLS verification at the operating system's certificate
store. Verification is never disabled.

## Modelling

### One match fact for every competition

`fact_matches` holds every match; `competition_code` carries the distinction.
The grain is the same everywhere and most questions span leagues, so
per-competition tables would only add UNIONs.

### A team-grain fact alongside the match fact

`fact_team_matches` has one row per team per match. Questions about a team
("goals scored by Arsenal", "home form") are sums over one column with one
relationship to `dim_teams`. On `fact_matches` the same question needs the home
and away columns added together under two relationships, one of them inactive
in a BI tool. `fact_matches` stays because match-level questions (total goals,
home win rate) are simpler there.

### fact_standings is derived from results

The standings endpoint returns only the current table, so it can't give a
matchday-by-matchday history. Before a season starts it also returns the
previous season's final numbers under the new season's id. Deriving the table
from results gives a full history and uses the same match data as every other
mart. The endpoint is still loaded, and a test reconciles the two (see
[testing-and-quality.md](testing-and-quality.md)).

### Snapshots are taken as of a date

A matchday is a label, and postponed games carry it for weeks. Summing "every
game labelled N or earlier" produces tables that never existed and that change
retroactively when a postponed game is played. Each snapshot is instead taken
at a date near the end of its round and counts every result played by then,
so past snapshots are stable and a team with a postponed game shows a game in
hand, as it did at the time. The date comes from a heuristic; see the
limitations below. The mechanism is in [data-model.md](data-model.md).

### Snapshots run without gaps

Snapshots cover matchday 1 to the latest matchday where most fixtures have
been played, and every label in between gets one. A round postponed whole
keeps the previous table, and one game played early from a later round doesn't
create a snapshot for that round on its own. A BI matchday axis therefore has
no holes, and the latest label always means a round that has mostly happened.

### The build is linear

Each result is assigned to exactly one snapshot and window sums produce the
running totals. The alternative, joining every snapshot to every earlier
result, joins a number of rows that grows with the square of the number of
matchdays.

### AWARDED counts as a result

`has_result` is true for `FINISHED` and `AWARDED`. An awarded match is an
officially decided result and the leagues count it. Scores are deliberately
left out of `has_result`: a result with missing scores fails
`assert_results_have_scores` and doesn't quietly drop out of the table.

### Points from winner, W/D/L from scores

Points are computed from the API's `winner` field and wins, draws and losses
from the scores. Using two fields makes `points = 3 * won + drawn` a real check
on the data. Computing both from the scores would make that test always pass.

### Incremental by season with delete+insert

`fact_standings` uses `unique_key = [competition_code, season_id]` and
`delete+insert`. One corrected result changes every later snapshot in its
season, so the season is the unit of rebuild. With the season as the key,
delete+insert removes all of its old rows, including matchday rows that no
longer exist after a snapshot date moves. A key per matchday row would leave
those orphans behind, and `merge` would need update logic for the same
outcome.

A season is rebuilt when any of its matches has a newer `_loaded_at` than the
table, or when its number of results differs from the `played` total of its
latest snapshot. The second condition covers a match deleted upstream, which
moves no `_loaded_at`.

### Status is normalised in staging, and the test fails the build

The free tier sometimes returns a kickoff timestamp in the match `status`
field for future fixtures. `stg_matches` maps those to `SCHEDULED` and keeps
the original in `status_raw`. With the known quirk handled, the
`accepted_values` test on `status` runs at error severity, so a genuinely new
status fails the build.

### Every mart has an enforced contract

Column names and types of the seven marts are declared in
`_marts__models.yml`, and dbt refuses to build a mart that doesn't match. The
marts are what the Parquet export and a BI model depend on, so a type change
has to be an explicit edit.

### Freshness is measured on the run log

`_loaded_at` only moves when content changes, and in an international break
nothing changes for two weeks while ingestion is healthy. Freshness on the data
tables would warn for the wrong reason, so it is measured on
`raw._load_runs.finished_at` for successful runs.

### Orphaned mart tables are dropped

The warehouse is carried from night to night, so a renamed model would leave
its old table behind for good. An `on-run-end` hook (`drop_orphan_marts`)
drops any table or view in `marts` that no model builds.

### Clean schema names

A `generate_schema_name` macro emits `staging`, `intermediate` and `marts`
verbatim. dbt's default prefix (`main_staging`) prevents developers clobbering
each other in a shared warehouse, which doesn't apply to one local file.

## Operations

### The nightly run is started from outside GitHub

GitHub's `schedule` trigger is best effort and, for this repository, starts
runs several hours late. The run needs to start at 02:00 SAST, after the
evening games, so an external cron service calls the `workflow_dispatch` API at
that time. The `schedule` entry stays as a fallback, and a `decide` job skips it
when that night's run has already succeeded. The cost is an outside dependency
and a token to renew; if either lapses, the fallback still runs, late.

### State lives in the Actions cache

The nightly pipeline restores the previous warehouse and JSON cache at the
start of a run and saves them only if the run succeeds. A failed run can't
overwrite good state, and the completed seasons aren't re-fetched every day.
The Actions cache is the simplest store that needs no infrastructure. Its cost
is eviction, covered below.

### Exact versions everywhere

`requirements.txt` and `requirements-dev.txt` hold the ranges a person edits.
`requirements.lock` and `requirements-dev.lock` pin every package, including
dbt's dependencies, resolved with `uv pip compile --universal` for Python 3.11
on any platform. CI and the pipeline install the lock files and read the
Python version from `.python-version`, so a dependency release can't change a
nightly build without a commit.

### Single writer

DuckDB allows one writer. Steps run as separate sequential processes, the
export opens the file read-only, and the workflow's concurrency group stops two
pipeline runs overlapping.

## Known limitations

- **Snapshot dates are a heuristic.** A round ends at its last game within 3
  days of the round's median kickoff date. Games played more than 3 days after
  the median are treated as rescheduled and count in the next snapshot, so a round spread over
  more than a week shows games in hand that were never really outstanding.
- **Ties share a position.** `rank()` orders by points, goal difference and
  goals scored. Head-to-head and other league-specific tie-breaks are not
  modelled, so positions can differ from the official table when teams are
  level.
- **Points deductions are not modelled.** Points come only from results. The
  reconciliation test and `assert_standings_points_consistent` would both fail
  if a league deducted points.
- **No history.** `dim_teams` is Type 1 and raw keeps only the current payload
  per key, so a renamed club shows its new name for every season.
- **State can be evicted.** GitHub removes caches unused for 7 days. The next
  run then finds no warehouse and bootstraps the completed seasons
  from the API (30 requests, a few minutes at the rate limit).
- **Whole-season pulls.** Every run fetches each competition's full season.
  With five leagues that is 15 requests a run; date-windowed extraction would
  matter only at a larger scale.
- **The 02:00 start depends on an outside service.** The external cron
  service and its fine-grained GitHub token are outside the repository. If the
  call fails or the token expires, the `schedule` fallback runs the pipeline
  hours late.
- **Single-writer DuckDB file.** Nothing runs in parallel against the
  warehouse.
- **UTC dates.** `kickoff_date` is the UTC date, which can differ from the local
  date for a kickoff near midnight.
- **Reconciliation assumes one run.** The test compares matches and standings
  as if they came from the same ingestion run. Loading one endpoint without the
  other can make it fail for timing reasons.
- **Staleness is a warning.** The nightly run checks how old the restored
  warehouse is and warns when a night was missed, but GitHub doesn't email
  about warnings. A run that doesn't happen at all is only noticed through
  cron-job.org's failure email or the next run's warning.
- **No BI model in the repo.** A Power BI model was started over the marts and
  is paused. [exports.md](exports.md) records its relationship design.
