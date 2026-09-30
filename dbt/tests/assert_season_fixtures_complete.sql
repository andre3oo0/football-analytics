-- A double round-robin league with n teams has n(n-1) fixtures: every team
-- plays n-1 home and n-1 away, across 2(n-1) matchdays of n/2 fixtures each.
-- Fixtures exist in the API from the start of a season (scheduled or played),
-- so this holds for in-progress seasons too. A failure means matches went
-- missing or were duplicated upstream.

with fixtures as (
    select * from {{ ref('fact_matches') }} where stage = 'REGULAR_SEASON'
),

season_size as (
    select competition_code, season_id,
           count(distinct home_team_id) as n_teams,
           count(*)                     as n_fixtures,
           count(distinct matchday)     as n_matchdays
    from fixtures
    group by competition_code, season_id
),

per_team as (
    select competition_code, season_id, team_id,
           count(*) filter (where is_home)     as home_games,
           count(*) filter (where not is_home) as away_games
    from {{ ref('fact_team_matches') }}
    where stage = 'REGULAR_SEASON'
    group by competition_code, season_id, team_id
),

per_matchday as (
    select competition_code, season_id, matchday, count(*) as n_fixtures
    from fixtures
    group by competition_code, season_id, matchday
)

select competition_code, season_id, null::bigint as team_id, null::integer as matchday,
       'season has ' || n_fixtures || ' fixtures over ' || n_matchdays
       || ' matchdays for ' || n_teams || ' teams' as problem
from season_size
where n_fixtures <> n_teams * (n_teams - 1)
   or n_matchdays <> 2 * (n_teams - 1)

union all

select t.competition_code, t.season_id, t.team_id, null,
       'team has ' || home_games || ' home / ' || away_games || ' away games'
from per_team t
join season_size s using (competition_code, season_id)
where home_games <> s.n_teams - 1 or away_games <> s.n_teams - 1

union all

select m.competition_code, m.season_id, null, m.matchday,
       'matchday has ' || m.n_fixtures || ' fixtures'
from per_matchday m
join season_size s using (competition_code, season_id)
where m.n_fixtures <> s.n_teams / 2
