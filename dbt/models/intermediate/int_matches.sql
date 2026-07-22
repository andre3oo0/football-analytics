-- Match-level derivations that don't belong in thin staging. Everything is
-- null-safe: an unplayed match has null scores, so its goals and points stay
-- null rather than becoming a fake 0.

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

    -- has_result means the match has a definitive outcome and should count
    -- toward standings. FINISHED is the usual case; AWARDED is an officially
    -- decided result (e.g. a forfeit with a set scoreline) and counts too,
    -- otherwise a league table would come out wrong. Anything else (SCHEDULED,
    -- postponed, ...) doesn't count.
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
