-- Intermediate: match-level business logic (derivations that do not belong in
-- thin staging). All measures are null-safe: an unplayed match has null scores
-- and therefore null goals/points, never a fabricated 0.

with matches as (
    select * from {{ ref('stg_matches') }}
)

select
    match_id,
    competition_code,
    season_id,
    kickoff_utc,
    status,
    stage,
    group_name,
    matchday,
    home_team_id,
    home_team_name,
    away_team_id,
    away_team_name,
    winner,
    duration,
    home_score_ft,
    away_score_ft,
    home_score_ht,
    away_score_ht,

    -- derived, null-safe measures
    -- has_result = the match has a definitive outcome and therefore counts
    -- toward standings. FINISHED is the normal case; AWARDED is an officially
    -- decided result (e.g. a forfeit with an awarded scoreline) and must count
    -- too — excluding it would make a league table wrong. SCHEDULED (and any
    -- other not-yet-decided status) is excluded.
    (status in ('FINISHED', 'AWARDED'))                     as has_result,
    home_score_ft + away_score_ft                           as total_goals_ft,
    case when winner = 'HOME_TEAM' then 3
         when winner = 'DRAW'      then 1
         when winner = 'AWAY_TEAM' then 0
    end                                                     as home_points,
    case when winner = 'AWAY_TEAM' then 3
         when winner = 'DRAW'      then 1
         when winner = 'HOME_TEAM' then 0
    end                                                     as away_points,

    _loaded_at
from matches
