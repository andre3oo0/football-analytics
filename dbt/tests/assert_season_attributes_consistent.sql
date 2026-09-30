-- Every match of a season carries the same season start and end date.
-- int_seasons relies on that when it collapses them to one row per season.

select competition_code, season_id,
       count(distinct season_start_date) as n_start_dates,
       count(distinct season_end_date)   as n_end_dates
from {{ ref('stg_matches') }}
group by competition_code, season_id
having count(distinct season_start_date) > 1
    or count(distinct season_end_date) > 1
