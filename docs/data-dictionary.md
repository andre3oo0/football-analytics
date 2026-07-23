# Data dictionary

Every table and column in the warehouse, with DuckDB types. Types are as built
by the current models. Columns prefixed `_` are pipeline metadata.

## raw schema

Landed API payloads. Each row is a natural key plus the untouched JSON. The
`PRIMARY KEY` on each table is what makes ingestion idempotent.

### raw.teams — PK (team_id)

| Column | Type | Notes |
|--------|------|-------|
| team_id | BIGINT | football-data.org global team id (natural key) |
| competition_code | VARCHAR | competition this team was pulled under |
| payload | JSON | full team object from `/competitions/{id}/teams` |
| _source_file | VARCHAR | cache filename the row came from |
| _loaded_at | TIMESTAMP | when the loader wrote the row |

### raw.matches — PK (match_id)

| Column | Type | Notes |
|--------|------|-------|
| match_id | BIGINT | global match id (natural key) |
| competition_code | VARCHAR | competition the match belongs to |
| payload | JSON | full match object (stage, status, score, teams, season) |
| _source_file | VARCHAR | cache filename |
| _loaded_at | TIMESTAMP | load timestamp |

### raw.standings — PK (competition_code, season_id, team_id, matchday, standing_type)

| Column | Type | Notes |
|--------|------|-------|
| competition_code | VARCHAR | competition code |
| season_id | BIGINT | season id from the response |
| team_id | BIGINT | team id from the table row |
| matchday | INTEGER | snapshot matchday (coalesced to 0 if null) |
| standing_type | VARCHAR | API table type: TOTAL, HOME, or AWAY |
| stage | VARCHAR | stage of the standings entry |
| group_name | VARCHAR | group, for tournament tables |
| payload | JSON | the single standings table row |
| _source_file | VARCHAR | cache filename |
| _loaded_at | TIMESTAMP | load timestamp |

## staging schema

Thin typed views, 1:1 with raw. Rename, cast and unpack only.

### staging.stg_teams

| Column | Type |
|--------|------|
| team_id | BIGINT |
| competition_code | VARCHAR |
| team_name | VARCHAR |
| short_name | VARCHAR |
| tla | VARCHAR |
| crest_url | VARCHAR |
| founded_year | INTEGER |
| venue | VARCHAR |
| club_colors | VARCHAR |
| website | VARCHAR |
| area_name | VARCHAR |
| _source_file | VARCHAR |
| _loaded_at | TIMESTAMP |

### staging.stg_matches

| Column | Type | Notes |
|--------|------|-------|
| match_id | BIGINT | |
| competition_code | VARCHAR | |
| season_id | BIGINT | |
| season_start_date | DATE | from the season object |
| season_end_date | DATE | from the season object |
| season_current_matchday | INTEGER | from the season object |
| kickoff_utc | TIMESTAMP | |
| status | VARCHAR | SCHEDULED / FINISHED / AWARDED (observed) |
| stage | VARCHAR | REGULAR_SEASON or a World Cup round |
| group_name | VARCHAR | |
| matchday | INTEGER | |
| home_team_id | BIGINT | |
| home_team_name | VARCHAR | |
| away_team_id | BIGINT | |
| away_team_name | VARCHAR | |
| winner | VARCHAR | HOME_TEAM / AWAY_TEAM / DRAW; null if unplayed |
| duration | VARCHAR | REGULAR / EXTRA_TIME / PENALTY_SHOOTOUT |
| home_score_ft | INTEGER | null until played |
| away_score_ft | INTEGER | null until played |
| home_score_ht | INTEGER | null until played |
| away_score_ht | INTEGER | null until played |
| _source_file | VARCHAR | |
| _loaded_at | TIMESTAMP | |

### staging.stg_standings

| Column | Type | Notes |
|--------|------|-------|
| competition_code | VARCHAR | |
| season_id | BIGINT | |
| team_id | BIGINT | |
| matchday | INTEGER | |
| standing_type | VARCHAR | TOTAL / HOME / AWAY |
| is_total_standing | BOOLEAN | true for the TOTAL table |
| stage | VARCHAR | |
| group_name | VARCHAR | |
| position | INTEGER | as reported by the endpoint |
| played_games | INTEGER | |
| won | INTEGER | |
| draw | INTEGER | |
| lost | INTEGER | |
| points | INTEGER | |
| goals_for | INTEGER | |
| goals_against | INTEGER | |
| goal_difference | INTEGER | |
| recent_form | VARCHAR | |
| team_name | VARCHAR | |
| _source_file | VARCHAR | |
| _loaded_at | TIMESTAMP | |

Note: nothing downstream consumes `stg_standings`; standings are derived from
match results instead. It is kept as a faithful copy of the endpoint.

## intermediate schema

### intermediate.int_seasons

| Column | Type | Notes |
|--------|------|-------|
| competition_code | VARCHAR | |
| season_id | BIGINT | |
| season_start_date | DATE | min across the season's matches |
| season_end_date | DATE | max across the season's matches |
| current_matchday | INTEGER | max across the season's matches |
| season_label | VARCHAR | e.g. "2024/25" or "2026" |

### intermediate.int_matches

Same columns as `stg_matches` (minus the season-date columns) plus the derived
measures:

| Column | Type | Notes |
|--------|------|-------|
| has_result | BOOLEAN | status in (FINISHED, AWARDED) |
| total_goals_ft | INTEGER | home + away full-time goals; null until played |
| home_points | INTEGER | 3/1/0 from winner; null until played |
| away_points | INTEGER | 3/1/0 from winner; null until played |

## marts schema

### marts.dim_competitions — PK (competition_code)

| Column | Type | Notes |
|--------|------|-------|
| competition_code | VARCHAR | primary key |
| competition_name | VARCHAR | |
| competition_type | VARCHAR | LEAGUE or TOURNAMENT |

### marts.dim_teams — PK (team_id)

| Column | Type |
|--------|------|
| team_id | BIGINT |
| team_name | VARCHAR |
| short_name | VARCHAR |
| tla | VARCHAR |
| area_name | VARCHAR |
| founded_year | INTEGER |
| venue | VARCHAR |
| club_colors | VARCHAR |
| crest_url | VARCHAR |
| website | VARCHAR |

### marts.dim_seasons — PK (season_id)

| Column | Type | Notes |
|--------|------|-------|
| season_id | BIGINT | primary key |
| competition_code | VARCHAR | FK to dim_competitions |
| season_label | VARCHAR | |
| season_start_date | DATE | |
| season_end_date | DATE | |
| current_matchday | INTEGER | |

### marts.fact_matches — grain (match_id)

| Column | Type | Notes |
|--------|------|-------|
| match_id | BIGINT | grain / degenerate key |
| competition_code | VARCHAR | FK to dim_competitions |
| season_id | BIGINT | FK to dim_seasons |
| home_team_id | BIGINT | FK to dim_teams |
| away_team_id | BIGINT | FK to dim_teams |
| stage | VARCHAR | |
| group_name | VARCHAR | |
| status | VARCHAR | |
| matchday | INTEGER | |
| kickoff_utc | TIMESTAMP | |
| winner | VARCHAR | |
| duration | VARCHAR | |
| home_score_ft | INTEGER | null until played |
| away_score_ft | INTEGER | null until played |
| home_score_ht | INTEGER | null until played |
| away_score_ht | INTEGER | null until played |
| total_goals_ft | INTEGER | null until played |
| home_points | INTEGER | null until played |
| away_points | INTEGER | null until played |
| has_result | BOOLEAN | FINISHED or AWARDED |
| _loaded_at | TIMESTAMP | carried from raw, used as the incremental watermark |

### marts.fact_standings — PK (standing_key)

Measure types are BIGINT/HUGEINT because they come from `count()`/`sum()`.

| Column | Type | Notes |
|--------|------|-------|
| standing_key | VARCHAR | `competition|season|team|matchday` |
| competition_code | VARCHAR | FK to dim_competitions |
| season_id | BIGINT | FK to dim_seasons |
| team_id | BIGINT | FK to dim_teams |
| matchday | INTEGER | matchday of this cumulative snapshot |
| played | BIGINT | cumulative games played |
| won | BIGINT | cumulative wins |
| drawn | BIGINT | cumulative draws |
| lost | BIGINT | cumulative losses |
| goals_for | HUGEINT | cumulative goals for |
| goals_against | HUGEINT | cumulative goals against |
| goal_difference | HUGEINT | goals_for - goals_against |
| points | HUGEINT | won*3 + drawn |
| position | BIGINT | rank by points, then GD, then goals for |
| _loaded_at | TIMESTAMP | max load time of the season's contributing matches |
