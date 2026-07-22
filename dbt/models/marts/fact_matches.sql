-- One row per match across every competition (leagues and the World Cup in the
-- same table). The stage column tells REGULAR_SEASON apart from the World Cup
-- rounds. Scores and measures are null until a match is played. Grain is
-- match_id, a degenerate key.
--
-- I keep both in one fact because the grain is the same (a match is a match)
-- and most questions span competitions ("goals per matchday", "results by
-- stage"). Splitting by competition would just force UNIONs to answer anything
-- cross-competition; stage plus the competition FK carry the distinction.

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
