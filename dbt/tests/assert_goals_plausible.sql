-- Goals should look like football. Top-flight European leagues average about
-- 2.4 to 3.3 goals a match over a season, and a double-digit total in a single
-- match is almost unheard of. A value outside these bands points at a data
-- problem (swapped or concatenated scores, a unit change in the feed) rather
-- than a real result.
--
--   * one match: more than 12 full-time goals
--   * one season with at least 100 results: an average outside 1.8 to 4.0
--
-- Seasons with fewer results are skipped, because a handful of matchdays can
-- legitimately average well above or below the long-run figure.

with results as (
    select match_id, competition_code, season_id, total_goals_ft
    from {{ ref('fact_matches') }}
    where has_result
),

season_averages as (
    select competition_code, season_id,
           count(*)            as n_results,
           avg(total_goals_ft) as avg_goals
    from results
    group by competition_code, season_id
)

select competition_code, season_id, match_id,
       total_goals_ft::double as value,
       'match has more than 12 goals' as problem
from results
where total_goals_ft > 12

union all

select competition_code, season_id, null,
       round(avg_goals, 2),
       'season averages ' || round(avg_goals, 2) || ' goals over '
       || n_results || ' results'
from season_averages
where n_results >= 100
  and (avg_goals < 1.8 or avg_goals > 4.0)
