-- A World Cup knockout match, once finished, can't be a draw and must have a
-- winner (extra time or penalties settle it). This catches stage/score
-- inconsistencies, like a mislabelled knockout row or a null winner on a
-- completed tie. Any rows returned mean the test failed.

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
