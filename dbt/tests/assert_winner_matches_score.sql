-- The API's `winner` field must agree with the full-time score. Points are
-- derived from `winner` and W/D/L from the scores, so a disagreement would
-- make the standings inconsistent.

select match_id, winner, home_score_ft, away_score_ft
from {{ ref('fact_matches') }}
where has_result
  and duration = 'REGULAR'
  and winner is distinct from case
        when home_score_ft > away_score_ft then 'HOME_TEAM'
        when home_score_ft < away_score_ft then 'AWAY_TEAM'
        else 'DRAW'
      end
