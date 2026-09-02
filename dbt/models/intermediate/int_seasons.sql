-- Collapse the season attributes down to one row per competition-season. The
-- season object repeats identically on every match of a season, so this dedup
-- belongs here rather than in staging.

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
        min(season_start_date)          as season_start_date,
        max(season_end_date)            as season_end_date,
        max(season_current_matchday)    as current_matchday
    from matches
    group by competition_code, season_id
)

select
    *,
    -- Readable label. A season inside a single calendar year is just that year;
    -- a cross-year league season is "YYYY/YY".
    case
        when extract(year from season_start_date) = extract(year from season_end_date)
            then cast(extract(year from season_start_date) as varchar)
        else cast(extract(year from season_start_date) as varchar)
             || '/' || right(cast(extract(year from season_end_date) as varchar), 2)
    end as season_label
from deduped
