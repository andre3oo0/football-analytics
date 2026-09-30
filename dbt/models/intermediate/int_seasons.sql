-- One row per competition-season from the season object repeated on every
-- match. Start and end dates are identical across a season's matches (tested
-- in assert_season_attributes_consistent), so any_value is safe. The API's
-- currentMatchday moves during a season and older payloads can lag, so the
-- highest value seen is the current one.

with matches as (
    select
        competition_code,
        season_id,
        season_start_date,
        season_end_date,
        season_current_matchday
    from {{ ref('stg_matches') }}
),

deduped as (
    select
        competition_code,
        season_id,
        any_value(season_start_date)    as season_start_date,
        any_value(season_end_date)      as season_end_date,
        max(season_current_matchday)    as current_matchday
    from matches
    group by competition_code, season_id
)

select
    *,
    -- "2024/25" for a cross-year season, "2025" for a calendar-year one.
    case
        when year(season_start_date) = year(season_end_date)
            then cast(year(season_start_date) as varchar)
        else cast(year(season_start_date) as varchar)
             || '/' || right(cast(year(season_end_date) as varchar), 2)
    end as season_label
from deduped
