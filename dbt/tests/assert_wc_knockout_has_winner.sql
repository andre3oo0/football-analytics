-- Singular test: a World Cup KNOCKOUT match, once FINISHED, cannot be a draw
-- and must have a winner (extra time / penalties decide it). This catches
-- stage/score inconsistencies — e.g. a knockout row mislabelled, or a null
-- winner on a completed tie. Returns offending rows; fails if any exist.

select
    f.match_id,
    f.competition_code,
    f.stage,
    f.status,
    f.winner
from {{ ref('fact_matches') }} f
join {{ ref('dim_competitions') }} c using (competition_code)
where c.competition_type = 'TOURNAMENT'
  and f.stage in ('LAST_32', 'LAST_16', 'QUARTER_FINALS',
                  'SEMI_FINALS', 'THIRD_PLACE', 'FINAL')
  and f.status = 'FINISHED'
  and (f.winner is null or f.winner = 'DRAW')
