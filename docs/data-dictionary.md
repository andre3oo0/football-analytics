# Data dictionary

Every table and column in the warehouse. Mart types are the `data_type` values
of the enforced contracts in `dbt/models/marts/_marts__models.yml`; dbt refuses
to build a mart whose output doesn't match. Staging and intermediate types are
what the casts produce. Columns prefixed `_` are pipeline metadata, and every
`_loaded_at` is naive UTC.

## raw schema

Created by `ingestion/loader.py`.

### raw.teams: PK (team_id)

| Column | Type | Notes |
|--------|------|-------|
| team_id | bigint | football-data.org team id |
| competition_code | varchar | competition the team was pulled under |
| payload | json | team object from `/competitions/{code}/teams` |
| _source_file | varchar | cache file name |
| _loaded_at | timestamp | when this payload last changed |

### raw.matches: PK (match_id)

| Column | Type | Notes |
|--------|------|-------|
| match_id | bigint | football-data.org match id |
| competition_code | varchar | |
| payload | json | match object (season, status, stage, teams, score) |
| _source_file | varchar | cache file name |
| _loaded_at | timestamp | when this payload last changed |

### raw.standings: PK (competition_code, season_id, team_id, matchday, standing_type)

| Column | Type | Notes |
|--------|------|-------|
| competition_code | varchar | |
| season_id | bigint | `season.id` of the response |
| team_id | bigint | |
| matchday | integer | `season.currentMatchday` of the snapshot; 0 if null |
| standing_type | varchar | TOTAL, HOME or AWAY |
| stage | varchar | |
| group_name | varchar | null for leagues |
| payload | json | one row of the standings table |
| _source_file | varchar | cache file name |
| _loaded_at | timestamp | when this payload last changed |

### raw._load_runs: PK (run_id)

| Column | Type | Notes |
|--------|------|-------|
| run_id | varchar | also printed in every log line of the run |
| started_at | timestamp | run start; the `_loaded_at` of every row the run wrote |
| finished_at | timestamp | freshness is measured on this for successful runs |
| status | varchar | `success` or `failed` |
| season | integer | `--season` value; null for the API's current season |
| refresh | boolean | whether `--refresh` was set |
| endpoints_loaded | integer | 0 for a failed run |
| rows_received | integer | 0 for a failed run |
| rows_changed | integer | rows inserted or rewritten; 0 for a failed run |
| rows_deleted | integer | matches deleted; 0 for a failed run |
| failures | varchar | one line per failed endpoint; null on success |

## staging schema

Views, 1:1 with raw.

### staging.stg_teams

| Column | Type |
|--------|------|
| team_id | bigint |
| competition_code | varchar |
| team_name | varchar |
| short_name | varchar |
| tla | varchar |
| crest_url | varchar |
| founded_year | integer |
| venue | varchar |
| club_colors | varchar |
| website | varchar |
| area_name | varchar |
| _source_file | varchar |
| _loaded_at | timestamp |

### staging.stg_matches

| Column | Type | Notes |
|--------|------|-------|
| match_id | bigint | |
| competition_code | varchar | |
| season_id | bigint | |
| season_start_date | date | from the season object |
| season_end_date | date | from the season object |
| season_current_matchday | integer | from the season object |
| kickoff_utc | timestamp | |
| stage | varchar | REGULAR_SEASON |
| group_name | varchar | |
| matchday | integer | |
| home_team_id | bigint | |
| home_team_name | varchar | |
| away_team_id | bigint | |
| away_team_name | varchar | |
| winner | varchar | HOME_TEAM, AWAY_TEAM or DRAW; null before kickoff |
| duration | varchar | REGULAR, EXTRA_TIME or PENALTY_SHOOTOUT |
| home_score_ft | integer | null before kickoff; the live score during play |
| away_score_ft | integer | null before kickoff; the live score during play |
| home_score_ht | integer | null before kickoff; the live score during play |
| away_score_ht | integer | null before kickoff; the live score during play |
| _source_file | varchar | |
| _loaded_at | timestamp | |
| status | varchar | normalised: a kickoff timestamp becomes SCHEDULED |
| status_raw | varchar | status exactly as the API sent it |
| kickoff_date | date | UTC date of kickoff |

### staging.stg_standings

| Column | Type | Notes |
|--------|------|-------|
| competition_code | varchar | |
| season_id | bigint | |
| team_id | bigint | |
| matchday | integer | |
| standing_type | varchar | TOTAL, HOME or AWAY |
| is_total_standing | boolean | true for TOTAL |
| stage | varchar | |
| group_name | varchar | |
| position | integer | as reported by the endpoint |
| played_games | integer | |
| won | integer | |
| draw | integer | |
| lost | integer | |
| points | integer | |
| goals_for | integer | |
| goals_against | integer | |
| goal_difference | integer | |
| recent_form | varchar | |
| team_name | varchar | |
| _source_file | varchar | |
| _loaded_at | timestamp | |

No model reads `stg_standings`; `assert_standings_reconcile_with_endpoint` does.

## intermediate schema

### intermediate.int_seasons

| Column | Type | Notes |
|--------|------|-------|
| competition_code | varchar | |
| season_id | bigint | |
| season_start_date | date | `any_value`; tested consistent across the season |
| season_end_date | date | `any_value`; tested consistent across the season |
| current_matchday | integer | highest value seen |
| season_label | varchar | "2024/25", or "2025" for a calendar-year season |

### intermediate.int_matches

`match_id`, `competition_code`, `season_id`, `kickoff_utc`, `kickoff_date`,
`status`, `stage`, `group_name`, `matchday`, the team ids and names, `winner`,
`duration` and the four scores, as in `stg_matches`, plus:

| Column | Type | Notes |
|--------|------|-------|
| has_result | boolean | status is FINISHED or AWARDED |
| total_goals_ft | integer | null before kickoff |
| home_points | integer | 3/1/0 from `winner` |
| away_points | integer | 3/1/0 from `winner` |
| _loaded_at | timestamp | |

## marts schema

### marts.dim_competitions: PK (competition_code)

| Column | Type | Notes |
|--------|------|-------|
| competition_code | varchar | e.g. PL |
| competition_name | varchar | |

### marts.dim_teams: PK (team_id)

| Column | Type | Notes |
|--------|------|-------|
| team_id | bigint | |
| team_name | varchar | |
| short_name | varchar | |
| tla | varchar | three-letter abbreviation |
| area_name | varchar | |
| founded_year | integer | |
| venue | varchar | |
| club_colors | varchar | |
| crest_url | varchar | |
| website | varchar | |

### marts.dim_seasons: PK (season_id)

| Column | Type | Notes |
|--------|------|-------|
| season_id | bigint | unique per competition |
| competition_code | varchar | FK to dim_competitions |
| season_label | varchar | e.g. "2024/25" |
| season_start_date | date | |
| season_end_date | date | |
| current_matchday | integer | API value at the latest load |

### marts.dim_date: PK (date_day)

| Column | Type | Notes |
|--------|------|-------|
| date_day | date | |
| year | integer | |
| quarter | integer | |
| month | integer | |
| month_name | varchar | |
| month_start | date | first day of the month |
| iso_day_of_week | integer | 1 = Monday ... 7 = Sunday |
| day_name | varchar | |
| is_weekend | boolean | Saturday or Sunday |
| week_start | date | Monday of the ISO week |

### marts.fact_matches: grain (match_id)

| Column | Type | Notes |
|--------|------|-------|
| match_id | bigint | degenerate dimension |
| competition_code | varchar | FK to dim_competitions |
| season_id | bigint | FK to dim_seasons |
| home_team_id | bigint | FK to dim_teams |
| away_team_id | bigint | FK to dim_teams (second role) |
| kickoff_date | date | FK to dim_date; UTC date |
| stage | varchar | |
| group_name | varchar | |
| status | varchar | normalised status |
| matchday | integer | fixture label; a postponed game keeps its original label |
| kickoff_utc | timestamp | |
| winner | varchar | |
| duration | varchar | |
| home_score_ft | integer | null before kickoff; the live score during play |
| away_score_ft | integer | null before kickoff; the live score during play |
| home_score_ht | integer | null before kickoff; the live score during play |
| away_score_ht | integer | null before kickoff; the live score during play |
| total_goals_ft | integer | null before kickoff |
| home_points | integer | 3/1/0 from `winner`; null while `winner` is null |
| away_points | integer | 3/1/0 from `winner`; null while `winner` is null |
| has_result | boolean | FINISHED or AWARDED |
| _loaded_at | timestamp | when raw last saw this match's payload change |

### marts.fct_team_matches: grain (match_id, team_id)

| Column | Type | Notes |
|--------|------|-------|
| match_id | bigint | FK to fact_matches |
| team_id | bigint | FK to dim_teams; the team the row is about |
| opponent_team_id | bigint | |
| competition_code | varchar | FK to dim_competitions |
| season_id | bigint | FK to dim_seasons |
| kickoff_date | date | FK to dim_date; UTC date |
| kickoff_utc | timestamp | |
| matchday | integer | |
| stage | varchar | |
| status | varchar | |
| is_home | boolean | |
| has_result | boolean | |
| goals_for | integer | null before kickoff; the live score during play |
| goals_against | integer | null before kickoff; the live score during play |
| goal_difference | integer | null before kickoff |
| points | integer | 3/1/0 from `winner`; null until `has_result` |
| result | varchar | W, D or L from the scores; null until `has_result` |
| _loaded_at | timestamp | |

### marts.fact_standings: grain (competition_code, season_id, team_id, matchday)

| Column | Type | Notes |
|--------|------|-------|
| competition_code | varchar | FK to dim_competitions |
| season_id | bigint | FK to dim_seasons |
| team_id | bigint | FK to dim_teams |
| matchday | integer | the matchday the snapshot follows |
| as_of_date | date | FK to dim_date; the date the snapshot is taken at |
| played | integer | cumulative |
| won | integer | cumulative |
| drawn | integer | cumulative |
| lost | integer | cumulative |
| goals_for | integer | cumulative |
| goals_against | integer | cumulative |
| goal_difference | integer | goals_for - goals_against |
| points | integer | cumulative; semi-additive, never sum across matchdays |
| position | integer | rank by points, goal difference, goals for; ties shared |
| _loaded_at | timestamp | latest raw change in the season; the incremental watermark |
