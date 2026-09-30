-- A match with a result (FINISHED/AWARDED) must have full-time scores and a
-- winner. If the API renamed or dropped a score field, the staging cast would
-- quietly produce nulls and standings would count the game with 0 goals; this
-- test turns that into a failure.

select match_id, status, winner, home_score_ft, away_score_ft
from {{ ref('fact_matches') }}
where has_result
  and (home_score_ft is null or away_score_ft is null or winner is null)
