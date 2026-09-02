-- One row per match across every competition, grain match_id (a degenerate
-- key). Scores and measures are null until a match is played.
--
-- Every competition shares this one table because the grain is identical (a
-- match is a match) and most questions span competitions ("goals per matchday",
-- "results by competition"). The competition FK carries the distinction, so
-- there is no need for per-competition fact tables and UNIONs to query across
-- them.

select
    match_id,                  -- grain / degenerate key

    -- foreign keys into the dimensions
    competition_code,          -- dim_competitions
    season_id,                 -- dim_seasons
    home_team_id,              -- dim_teams
    away_team_id,              -- dim_teams

    -- degenerate dimensions
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

    -- carried from raw for auditing and the incremental watermark
    _loaded_at
from {{ ref('int_matches') }}
