-- Singular test: in fact_standings, points must equal won*3 + drawn (3/1/0).
-- Internal-consistency check on the derived cumulative record.

select
    standing_key,
    points,
    won,
    drawn
from {{ ref('fact_standings') }}
where points <> won * 3 + drawn
