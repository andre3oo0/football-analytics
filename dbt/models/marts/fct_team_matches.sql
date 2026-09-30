-- One row per team per match: every match appears twice, once from each side.
-- This is the shape most team questions want ("goals scored by Arsenal",
-- "home form") without summing home and away columns under two relationships.
-- Unplayed fixtures are included with null measures, so a team's full
-- schedule is here too.
--
-- `result` (W/D/L) comes from the scores; `points` comes from the API's winner
-- field (via int_matches). They're independent, which is what makes
-- assert_standings_points_consistent a real check.

with matches as (
    select * from {{ ref('int_matches') }}
),

sides as (
    select
        match_id, competition_code, season_id, matchday, stage, status,
        kickoff_utc, kickoff_date, has_result, _loaded_at,
        home_team_id  as team_id,
        away_team_id  as opponent_team_id,
        true          as is_home,
        home_score_ft as goals_for,
        away_score_ft as goals_against,
        home_points   as points
    from matches
    union all
    select
        match_id, competition_code, season_id, matchday, stage, status,
        kickoff_utc, kickoff_date, has_result, _loaded_at,
        away_team_id, home_team_id, false,
        away_score_ft, home_score_ft, away_points
    from matches
)

select
    match_id,
    team_id,
    opponent_team_id,
    competition_code,
    season_id,
    kickoff_date,
    kickoff_utc,
    matchday,
    stage,
    status,
    is_home,
    has_result,
    goals_for,
    goals_against,
    goals_for - goals_against                        as goal_difference,
    -- A live match can already have a score and a provisional winner; it only
    -- gets points and a result once it has a definitive outcome.
    case when has_result then points end             as points,
    case
        when not has_result then null
        when goals_for > goals_against then 'W'
        when goals_for = goals_against then 'D'
        when goals_for < goals_against then 'L'
    end                                              as result,
    _loaded_at
from sides
