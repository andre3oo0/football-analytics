# Exports (serving layer)

The marts are exported to Parquet so a BI tool can consume them. The Power BI
report itself is out of scope for now; this page covers the export and how the
schema is set up for clean relationships.

## export_marts.py

A standalone script at the repo root. It:

- Opens `data/football.duckdb` with `read_only=True`, so it can never lock out or
  mutate the warehouse.
- Exports only the five mart tables (`fact_matches`, `fact_standings`,
  `dim_teams`, `dim_competitions`, `dim_seasons`) from the `marts` schema, each to
  `exports/<table>.parquet` via DuckDB `COPY ... (FORMAT PARQUET)`.
- Creates `exports/` if missing and prints each table's row count as it goes, so
  a run verifies itself.
- Is idempotent: re-running overwrites the files, counts unchanged.

It exports marts only, on purpose. This is the curated serving layer, not a
database dump, so raw/staging/intermediate are not exported.

```bash
python export_marts.py
```

`exports/*.parquet` is git-ignored (only `exports/.gitkeep` is committed), the
same way `data/raw/` is handled. The script is committed; its output is not.

## Row counts

| Table | Rows |
|-------|------|
| fact_matches | 3,608 |
| fact_standings | 3,504 |
| dim_teams | 164 |
| dim_competitions | 6 |
| dim_seasons | 11 |

## Relationships for a BI tool

Most foreign keys match the dimension key by name and type, so a BI tool
auto-detects them:

| Fact FK | Dimension | Dim key | Name match | Type match |
|---------|-----------|---------|------------|------------|
| fact_matches.competition_code | dim_competitions | competition_code | yes | yes (VARCHAR) |
| fact_matches.season_id | dim_seasons | season_id | yes | yes (BIGINT) |
| fact_matches.home_team_id | dim_teams | team_id | no | yes (BIGINT) |
| fact_matches.away_team_id | dim_teams | team_id | no | yes (BIGINT) |
| fact_standings.competition_code | dim_competitions | competition_code | yes | yes |
| fact_standings.season_id | dim_seasons | season_id | yes | yes |
| fact_standings.team_id | dim_teams | team_id | yes | yes |

The only mismatch is the two team foreign keys on `fact_matches`. That is a
role-playing dimension: a match points at `dim_teams` twice (home and away), so
they cannot both be called `team_id`. The types match, only the names differ.

The recommended handling is in the BI model, not in dbt: create two relationships
to `dim_teams[team_id]`, one active and one inactive, and switch between them in
measures (in Power BI, `USERELATIONSHIP`), or use two role-playing copies of the
dimension. Renaming in dbt would not help and would break the single-fact design.
This was left as-is on purpose.
