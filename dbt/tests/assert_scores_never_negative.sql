-- Singular test: a score is never negative. Null is allowed (match not played).
-- Returns offending rows; the test fails if any exist.

select
    match_id,
    home_score_ft,
    away_score_ft,
    home_score_ht,
    away_score_ht
from {{ ref('fact_matches') }}
where home_score_ft < 0
   or away_score_ft < 0
   or home_score_ht < 0
   or away_score_ht < 0
