-- Fact: ONE row per match across ALL competitions (leagues + World Cup in a
-- single table, as required). The `stage` column distinguishes REGULAR_SEASON
-- from the World Cup ladder. Scores/measures are nullable and stay null until a
-- match is played. Grain = match_id (a degenerate dimension / natural key).
--
-- One fact for both because the grain is identical (a match is a match) and the
-- questions are shared ("goals per matchday", "results by stage"). Splitting by
-- competition would fragment that grain and force UNION-ing to answer anything
-- cross-competition. `stage` + the competition FK carry the distinction instead.

select
    match_id,                  -- grain / degenerate key

    -- foreign keys into the dimensions
    competition_code,          -- -> dim_competitions
    season_id,                 -- -> dim_seasons
    home_team_id,              -- -> dim_teams
    away_team_id,              -- -> dim_teams

    -- degenerate dimensions
    stage,
    group_name,
    status,
    matchday,
    kickoff_utc,
    winner,
    duration,

    -- measures (nullable until played)
    home_score_ft,
    away_score_ft,
    home_score_ht,
    away_score_ht,
    total_goals_ft,
    home_points,
    away_points,
    has_result,

    -- audit / incremental watermark carried from raw
    _loaded_at
from {{ ref('int_matches') }}
