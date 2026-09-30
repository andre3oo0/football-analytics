# Exports

The marts are exported to Parquet for a BI tool. No Power BI file is
committed; the section below describes how a Power BI model over the marts is
set up.

## export_marts.py

```bash
python export_marts.py                                  # defaults
python export_marts.py --out exports/ --db path/to/football.duckdb
```

The script opens the warehouse read-only and writes one Parquet file per mart
to `exports/<table>.parquet` with DuckDB's `COPY ... (FORMAT PARQUET)`,
printing each table's row count. It exports the seven marts only: `fact_matches`,
`fact_team_matches`, `fact_standings`, `dim_teams`, `dim_competitions`,
`dim_seasons` and `dim_date`.

| Flag | Default |
|------|---------|
| `--db` | `DBT_DUCKDB_PATH` if set (a relative path is relative to `dbt/`, as in the dbt profile), otherwise `data/football.duckdb` |
| `--out` | `exports/` |

Re-running overwrites the files. `exports/*.parquet` is git-ignored. The
nightly pipeline uploads the files as the `marts-parquet` artifact, kept for
14 days.

## A Power BI model over the marts

### Relationships

All relationships are many-to-one from fact to dimension, filtering in one
direction (dimension to fact).

| From | To | Active |
|------|----|--------|
| `fact_matches.competition_code` | `dim_competitions.competition_code` | yes |
| `fact_matches.season_id` | `dim_seasons.season_id` | yes |
| `fact_matches.home_team_id` | `dim_teams.team_id` | yes |
| `fact_matches.away_team_id` | `dim_teams.team_id` | no |
| `fact_matches.kickoff_date` | `dim_date.date_day` | yes |
| `fact_team_matches.competition_code` | `dim_competitions.competition_code` | yes |
| `fact_team_matches.season_id` | `dim_seasons.season_id` | yes |
| `fact_team_matches.team_id` | `dim_teams.team_id` | yes |
| `fact_team_matches.kickoff_date` | `dim_date.date_day` | yes |
| `fact_standings.competition_code` | `dim_competitions.competition_code` | yes |
| `fact_standings.season_id` | `dim_seasons.season_id` | yes |
| `fact_standings.team_id` | `dim_teams.team_id` | yes |
| `fact_standings.as_of_date` | `dim_date.date_day` | yes |
| `dim_seasons.competition_code` | `dim_competitions.competition_code` | no |

Leave out a relationship between `fact_team_matches.match_id` and
`fact_matches.match_id`. The dbt test uses it to check integrity, but in the BI
model it would give `dim_date` and the other dimensions a second path into
`fact_team_matches` through `fact_matches`, which is ambiguous. The two facts
share dimensions, and that is enough to show them side by side.

### Competition has two paths

Each fact reaches `dim_competitions` directly and through `dim_seasons`. Power
BI allows only one active path, so one link has to be inactive. The model makes
`dim_seasons` to `dim_competitions` inactive, which breaks every triangle with
a single cut and keeps all fact-to-dimension links active. `competition_code`
is on every fact, so the direct link is the natural one to keep.

### Dates

Mark `dim_date` as the date table on `date_day` and turn off auto date/time for
the file, or Power BI adds a hidden date table per date column.

Each fact has one active relationship to `dim_date`: `kickoff_date` for
`fact_matches` and `fact_team_matches`, and `as_of_date` for `fact_standings`.
Filtering standings by date then means "the table as it stood on that date".
`kickoff_date` is the UTC date. The `_loaded_at` columns are pipeline audit
fields and get no date relationship.

### Team measures

Use `fact_team_matches` for anything about a team: goals scored and conceded,
points, form, home and away splits (`is_home`). It has one team column and one
active relationship to `dim_teams`. The same measures on `fact_matches` need the
home and away columns combined, with `USERELATIONSHIP` on the inactive
`away_team_id` relationship for the away side. Keep `fact_matches` for
match-level measures such as total goals or home win rate.

### Standings are semi-additive

`fact_standings` rows are cumulative snapshots. Summing `points`, `played` or
any other column across matchdays gives nonsense. A standings measure should
pick, per team, the latest snapshot in the current filter context (the highest
`matchday` within a competition-season, or the latest `as_of_date` up to the
selected date) and read that row. `position` is an ordinal and should never be
summed.

### Summarisation

Set every key and ordinal (`*_id`, `matchday`, `position`, `current_matchday`,
`founded_year`) to "Don't summarize", so a dragged-in column doesn't add up ids.
