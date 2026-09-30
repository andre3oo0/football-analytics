-- Snapshot dates must never go backwards as the matchday increases, and a
-- team's games played can't fall. Both follow from how as_of_date is built,
-- so a failure means that logic regressed.

with ordered as (
    select
        competition_code, season_id, team_id, matchday, as_of_date, played,
        lag(as_of_date) over w as prev_as_of_date,
        lag(played)     over w as prev_played
    from {{ ref('fact_standings') }}
    window w as (partition by competition_code, season_id, team_id order by matchday)
)

select *
from ordered
where as_of_date < prev_as_of_date
   or played < prev_played
