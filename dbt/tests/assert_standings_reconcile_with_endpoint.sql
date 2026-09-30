-- The derived table must agree with the standings endpoint. For every season
-- where fact_standings has rows, the latest derived snapshot is compared with
-- the latest TOTAL snapshot from the endpoint, team by team, on played, points,
-- goal difference and goals for.
--
-- One known, deliberate difference: the endpoint leaves AWARDED matches out of
-- its table, while the leagues count them (e.g. Union Berlin v Bochum,
-- Bundesliga 2024/25, awarded 0-2). fact_standings counts them, so their
-- contribution is subtracted here before comparing. Anything else that
-- differs (a missed or double-counted result, a points deduction) fails.
--
-- Assumes matches and standings come from the same ingestion run (the
-- default). The endpoint's pre-season snapshot is skipped because only
-- seasons with derived rows are compared.

with derived as (
    select *
    from {{ ref('fact_standings') }}
    qualify matchday = max(matchday) over (partition by competition_code, season_id)
),

awarded as (
    select competition_code, season_id, team_id,
           count(*)             as played,
           sum(points)          as points,
           sum(goal_difference) as goal_difference,
           sum(goals_for)       as goals_for
    from {{ ref('fact_team_matches') }}
    where status = 'AWARDED' and stage = 'REGULAR_SEASON'
    group by competition_code, season_id, team_id
),

derived_like_endpoint as (
    select
        d.competition_code, d.season_id, d.team_id,
        d.played          - coalesce(a.played, 0)          as played,
        d.points          - coalesce(a.points, 0)          as points,
        d.goal_difference - coalesce(a.goal_difference, 0) as goal_difference,
        d.goals_for       - coalesce(a.goals_for, 0)       as goals_for
    from derived d
    left join awarded a using (competition_code, season_id, team_id)
),

official as (
    select *
    from {{ ref('stg_standings') }}
    where is_total_standing
    qualify matchday = max(matchday) over (partition by competition_code, season_id)
),

compared_seasons as (
    select distinct competition_code, season_id from derived
    intersect
    select distinct competition_code, season_id from official
),

compared as (
    select
        coalesce(d.competition_code, o.competition_code) as competition_code,
        coalesce(d.season_id, o.season_id)               as season_id,
        coalesce(d.team_id, o.team_id)                   as team_id,
        d.played,          o.played_games    as official_played,
        d.points,          o.points          as official_points,
        d.goal_difference, o.goal_difference as official_goal_difference,
        d.goals_for,       o.goals_for       as official_goals_for
    from derived_like_endpoint d
    full outer join official o
        on  o.competition_code = d.competition_code
        and o.season_id        = d.season_id
        and o.team_id          = d.team_id
)

select c.*
from compared c
join compared_seasons using (competition_code, season_id)
where c.played          is distinct from c.official_played
   or c.points          is distinct from c.official_points
   or c.goal_difference is distinct from c.official_goal_difference
   or c.goals_for       is distinct from c.official_goals_for
