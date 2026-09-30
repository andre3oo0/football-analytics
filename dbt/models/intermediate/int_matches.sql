-- Match-level derivations that don't belong in thin staging. Everything is
-- null-safe: an unplayed match has null scores, so its goals and points stay
-- null rather than becoming a fake 0.

with matches as (
    select
        *,
        -- A definitive outcome that counts toward standings. AWARDED is an
        -- officially decided result (e.g. a forfeit with a set scoreline) and
        -- counts like FINISHED. Scores are deliberately not part of this flag:
        -- a result with missing scores should fail a test, not quietly drop out.
        (status in ('FINISHED', 'AWARDED')) as has_result
    from {{ ref('stg_matches') }}
)

select
    match_id,
    competition_code,
    season_id,
    kickoff_utc,
    kickoff_date,
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

    has_result,
    home_score_ft + away_score_ft                           as total_goals_ft,
    -- Points come from the API's `winner`; win/draw/loss downstream come from
    -- the scores. Two independent fields, so a test can check they agree. A
    -- live match can already have a provisional winner, so points wait for a
    -- definitive result.
    case when not has_result          then null
         when winner = 'HOME_TEAM' then 3
         when winner = 'DRAW'      then 1
         when winner = 'AWAY_TEAM' then 0
    end                                                     as home_points,
    case when not has_result          then null
         when winner = 'AWAY_TEAM' then 3
         when winner = 'DRAW'      then 1
         when winner = 'HOME_TEAM' then 0
    end                                                     as away_points,

    _loaded_at
from matches
