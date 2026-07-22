-- A team's cumulative games played should never go down as the matchday
-- increases. This guards the cumulative logic against a regression that would
-- let a later matchday lose earlier results.

with ordered as (
    select
        competition_code,
        season_id,
        team_id,
        matchday,
        played,
        lag(played) over (
            partition by competition_code, season_id, team_id
            order by matchday
        ) as prev_played
    from {{ ref('fact_standings') }}
)

select *
from ordered
where played < prev_played
