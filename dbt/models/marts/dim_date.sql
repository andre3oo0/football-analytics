-- One row per calendar day, covering every season and every kickoff (some
-- opening fixtures are played a day or two before the API's season start
-- date). Facts join on kickoff_date, the UTC date of kickoff, which for a late
-- kickoff can differ from the local calendar day.

with bounds as (
    select
        least((select min(season_start_date) from {{ ref('int_seasons') }}),
              (select min(kickoff_date) from {{ ref('stg_matches') }}))    as first_day,
        greatest((select max(season_end_date) from {{ ref('int_seasons') }}),
                 (select max(kickoff_date) from {{ ref('stg_matches') }})) as last_day
),

days as (
    select unnest(generate_series(first_day, last_day, interval 1 day))::date as date_day
    from bounds
)

select
    date_day,
    year(date_day)::integer                      as year,
    quarter(date_day)::integer                   as quarter,
    month(date_day)::integer                     as month,
    monthname(date_day)                          as month_name,
    date_trunc('month', date_day)::date          as month_start,
    isodow(date_day)::integer                    as iso_day_of_week,   -- 1 = Monday
    dayname(date_day)                            as day_name,
    (isodow(date_day) in (6, 7))                 as is_weekend,
    date_trunc('week', date_day)::date           as week_start          -- ISO week, Monday
from days
