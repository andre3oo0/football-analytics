# Design decisions

The decisions that shaped the project, each with the reasoning and the
alternatives that were considered. The point of writing them down is that every
one should be defensible.

## Idempotent ingestion via table primary keys

**Decision.** Loads upsert by natural key with `INSERT ... ON CONFLICT DO
UPDATE`, and the natural key is a `PRIMARY KEY` on each raw table.

**Why.** Idempotency should be guaranteed by the storage, not by convention. With
the constraint in place, a duplicate cannot exist even if the loader is called
wrongly. Re-running is always safe.

**Alternatives.** Append-only with dedup downstream (fragile, and duplicates
exist transiently), or truncate-and-reload (loses the cheap incremental story and
re-hits the API).

## Raw stores the payload as JSON, not flattened columns

**Decision.** Each raw row is the natural key plus the untouched API payload as
`JSON`.

**Why.** It keeps ingestion generic and resistant to API shape changes, and it
pushes every field-level decision into dbt where it is tested and documented.

**Alternatives.** Flattening in Python couples ingestion to the API schema and
scatters interpretation across two languages.

## One fact table for every competition

**Decision.** `fact_matches` holds every match from every competition; the
competition foreign key carries the distinction.

**Why.** The grain is identical (a match is a match) and most questions span
competitions. A single table answers them without UNIONs.

**Alternatives.** Per-competition fact tables fragment the grain and duplicate
logic.

## fact_standings is derived from match results

**Decision.** Compute each matchday's table by cumulating finished match results,
rather than reading the standings endpoint.

**Why.** The endpoint returns a single current table, and in the off-season it
returns last season's final numbers stamped with the new season at matchday 1,
which is self-contradictory. Deriving from results is internally consistent and
gives a real week-by-week progression. As a check, the derived tables match
reality: 2024/25 Premier League (Liverpool champions on 84 points) and 2025/26
Premier League (Arsenal champions on 85 points), each confirmed row-for-row
against the published final table.

**Consequence.** The standings endpoint data is still landed in `raw.standings`
(harmless), but nothing downstream uses it, so `stg_standings` is a leaf.

## AWARDED counts toward standings

**Decision.** `has_result = status in ('FINISHED', 'AWARDED')`.

**Why.** An AWARDED match (a forfeit with an official scoreline) is a real,
decided result. Excluding it would make a league table wrong by a game. This is a
deliberate widening of "only played matches count". Three matches are affected:
two in 2024/25 (BL1, FL1) and one in 2025/26 (FL1).

**Reversible.** Change the predicate in `int_matches.sql` if strict
FINISHED-only is preferred.

## delete+insert for the incremental fact

**Decision.** `fact_standings` is incremental with `unique_key = standing_key`
and `incremental_strategy = delete+insert`; a whole season is re-derived when its
results change.

**Why.** delete+insert replaces the keys in the incoming batch, so a re-fetched
matchday updates in place and never duplicates. The whole season is recomputed
because a corrected early result cascades to every later matchday's totals.

**Alternatives.** `append` would duplicate re-fetched matchdays; `merge` would
add per-column update SQL for no benefit on a single surrogate key.

## dim_competitions from a seed

**Decision.** Build `dim_competitions` from `seed_competitions.csv`.

**Why.** `competition_type` (LEAGUE vs TOURNAMENT) is our classification, not an
API field, and the list is small static reference data, which is exactly what
seeds are for. It also decouples the dimension from whether a competition happens
to have match rows.

## Clean schema names via a macro

**Decision.** A `generate_schema_name` macro emits `staging` / `intermediate` /
`marts` verbatim instead of dbt's default `main_staging` concatenation.

**Why.** The default guards against developers clobbering each other in a shared
warehouse. That risk does not exist for a single local file, so the cleaner names
win for a readable lineage graph.

## accepted_values on the enum columns

**Decision.** Keep an `accepted_values` list on the enum-like columns. `stage`
fails the build on an unlisted value; `status` only warns.

**Why.** The original idea was to fail loudly so a shift in the data gets noticed
rather than silently accepted. That holds for `stage`, which is stable and clean.
It does not hold for `status`: it is a live, source-controlled field, and on the
free tier the API is not clean about it — besides the real lifecycle values it
sometimes returns a kickoff timestamp in the `status` field for future fixtures.
Failing the build on that would make CI red for a source quirk we can't control
and that doesn't affect the model (nothing downstream trusts a raw status beyond
`has_result`, i.e. FINISHED/AWARDED). So `status` runs at `severity: warn`: the
unexpected values still show up in the run output, but they don't block the
pipeline. `stage` stays a hard failure.

## Backfill one completed season

**Decision.** Ingest the completed 2024/25 and 2025/26 league seasons alongside
the live 2026/27 data.

**Why.** The leagues are mid-off-season with no finished matches, so a
match-derived standings table would be empty. The backfills supply real finished
results to build and demonstrate against, while the live season is kept for the
scheduling story. `dim_teams` unions teams across seasons so relegated sides
still resolve foreign keys — verified across three seasons, including a club that
left and returned (Ipswich Town), which still resolves to a single `dim_teams`
row. Each completed season derives its own independent `fact_standings`
progression.

## Single-writer discipline

**Decision.** Every step runs as a separate sequential process; reads use
`read_only=True`; CI uses a concurrency group.

**Why.** DuckDB allows one writer. Respecting that avoids lock contention and the
"looks hung" symptom, and it is the pattern CI needs too.

## TLS via the OS trust store

**Decision.** Use `truststore` to verify against the OS trust store rather than
disabling verification.

**Why.** The dev network does SSL inspection, which breaks certifi. `truststore`
keeps verification on by trusting the OS store (which has the corporate root),
and is a no-op with public CAs elsewhere. Disabling verification would have been
the wrong fix.

## Open decisions

- The two team foreign keys on `fact_matches` (`home_team_id`, `away_team_id`)
  do not match `dim_teams.team_id` by name, because a match references teams in
  two roles. Left as-is; handled in the BI tool. See [exports.md](exports.md).
- Whether to keep AWARDED counting toward standings (documented above).
