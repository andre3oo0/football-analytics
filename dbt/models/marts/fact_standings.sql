-- Fact: league standings, DERIVED from match results (INCREMENTAL).
-- Grain: one row per (competition, season, team, matchday).
--
-- Why derived (not the API snapshot)
-- ----------------------------------
-- The standings endpoint returns a single "current" table. In the off-season it
-- reports last season's final numbers stamped with the new season/matchday 1 —
-- a contradiction. We instead COMPUTE each matchday's table from finished match
-- results, which is internally consistent and gives a real week-by-week
-- progression. The raw standings endpoint data still lands in raw.standings
-- (harmless), but nothing downstream depends on it any more.
--
-- Scope: LEAGUE competitions only, REGULAR_SEASON matchdays. The World Cup is
-- EXCLUDED by design (its group + knockout format does not yield a league
-- table this way); that exclusion is the `competition_type = 'LEAGUE'` +
-- `stage = 'REGULAR_SEASON'` filter below.
--
-- Contribution rule: only matches with a definitive result (has_result =
-- FINISHED or AWARDED) contribute. SCHEDULED matches never count.
--
-- For team T and matchday N, all measures are the CUMULATIVE record over every
-- contributing match with matchday <= N: played, won, drawn, lost, goals_for,
-- goals_against, goal_difference, points (3/1/0), and league position.
-- Tie-break for position: points DESC, then goal_difference DESC, then
-- goals_for DESC.
--
-- Incremental: delete+insert on standing_key. When new results land for a
-- season, that whole season is re-derived and its rows replaced — necessary
-- because a corrected early result cascades to every later matchday's
-- cumulative totals. See the header of the previous phase / README for the
-- strategy rationale.

{{ config(
    materialized = 'incremental',
    unique_key   = 'standing_key',
    incremental_strategy = 'delete+insert'
) }}

with league_results as (
    select
        f.competition_code,
        f.season_id,
        f.matchday,
        f.home_team_id,
        f.away_team_id,
        f.home_score_ft,
        f.away_score_ft,
        f.home_points,
        f.away_points,
        f._loaded_at
    from {{ ref('fact_matches') }} f
    join {{ ref('dim_competitions') }} c using (competition_code)
    where c.competition_type = 'LEAGUE'     -- excludes the World Cup
      and f.stage = 'REGULAR_SEASON'
      and f.has_result                       -- FINISHED or AWARDED only
),

{% if is_incremental() %}
-- Re-derive only seasons that received new/changed results since the last run.
seasons_to_refresh as (
    select distinct competition_code, season_id
    from league_results
    where _loaded_at > (select coalesce(max(_loaded_at), timestamp '1900-01-01') from {{ this }})
),
scoped as (
    select r.* from league_results r
    join seasons_to_refresh s using (competition_code, season_id)
),
{% else %}
scoped as (select * from league_results),
{% endif %}

-- one row per team per contributing match (home and away perspectives)
team_match as (
    select competition_code, season_id, matchday, home_team_id as team_id,
           home_score_ft as gf, away_score_ft as ga, home_points as pts, _loaded_at
    from scoped
    union all
    select competition_code, season_id, matchday, away_team_id as team_id,
           away_score_ft as gf, home_score_ft as ga, away_points as pts, _loaded_at
    from scoped
),

teams_in_season as (select distinct competition_code, season_id, team_id from team_match),
matchdays       as (select distinct competition_code, season_id, matchday from team_match),

-- every team x every matchday of its season (so a team gets a row at each
-- matchday even if a fixture was postponed — "games in hand" show correctly)
scaffold as (
    select t.competition_code, t.season_id, t.team_id, m.matchday
    from teams_in_season t
    join matchdays m using (competition_code, season_id)
),

cumulative as (
    select
        s.competition_code,
        s.season_id,
        s.team_id,
        s.matchday,
        count(tm.team_id)                            as played,
        count(tm.team_id) filter (where tm.pts = 3)  as won,
        count(tm.team_id) filter (where tm.pts = 1)  as drawn,
        count(tm.team_id) filter (where tm.pts = 0)  as lost,
        coalesce(sum(tm.gf), 0)                      as goals_for,
        coalesce(sum(tm.ga), 0)                      as goals_against,
        coalesce(sum(tm.gf - tm.ga), 0)              as goal_difference,
        coalesce(sum(tm.pts), 0)                     as points,
        max(tm._loaded_at)                           as _loaded_at
    from scaffold s
    left join team_match tm
        on  tm.competition_code = s.competition_code
        and tm.season_id        = s.season_id
        and tm.team_id          = s.team_id
        and tm.matchday        <= s.matchday
    group by 1, 2, 3, 4
)

select
    concat_ws('|', competition_code, cast(season_id as varchar),
                    cast(team_id as varchar), cast(matchday as varchar)) as standing_key,
    competition_code,
    season_id,
    team_id,
    matchday,
    played,
    won,
    drawn,
    lost,
    goals_for,
    goals_against,
    goal_difference,
    points,
    rank() over (
        partition by competition_code, season_id, matchday
        order by points desc, goal_difference desc, goals_for desc
    ) as position,
    _loaded_at
from cumulative
