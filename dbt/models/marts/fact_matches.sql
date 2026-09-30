-- One row per match across every competition. match_id is a degenerate
-- dimension: a key with no dimension table of its own. Scores and measures
-- are null until a match is played. For per-team questions use
-- fct_team_matches instead, which has one row per side.

select
    match_id,

    -- foreign keys
    competition_code,          -- dim_competitions
    season_id,                 -- dim_seasons
    home_team_id,              -- dim_teams (active in the BI model)
    away_team_id,              -- dim_teams (role-playing, inactive)
    kickoff_date,              -- dim_date (UTC date)

    -- low-cardinality descriptive attributes
    stage,
    group_name,
    status,
    matchday,
    kickoff_utc,
    winner,
    duration,

    -- measures (null until played)
    home_score_ft,
    away_score_ft,
    home_score_ht,
    away_score_ht,
    total_goals_ft,
    home_points,
    away_points,
    has_result,

    _loaded_at                 -- when raw last saw this match's payload change (UTC)
from {{ ref('int_matches') }}
