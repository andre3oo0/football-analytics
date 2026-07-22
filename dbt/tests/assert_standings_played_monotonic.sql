-- Singular test: a team's cumulative games played must never DECREASE as the
-- matchday increases. Guards the cumulative derivation against a regression
-- that would let later matchdays lose earlier results.

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
