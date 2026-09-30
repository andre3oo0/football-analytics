-- Every season's snapshots run 1, 2, ..., N with no gaps, and every team has a
-- row at each one, so a BI matchday axis never skips a value. fact_standings
-- builds the series from the fixture list, so a gap means that logic regressed.

with per_season as (
    select competition_code, season_id,
           min(matchday)            as first_matchday,
           max(matchday)            as last_matchday,
           count(distinct matchday) as n_matchdays,
           count(distinct team_id)  as n_teams,
           count(*)                 as n_rows
    from {{ ref('fact_standings') }}
    group by competition_code, season_id
)

select *
from per_season
where first_matchday <> 1
   or n_matchdays <> last_matchday
   or n_rows <> n_teams * n_matchdays
