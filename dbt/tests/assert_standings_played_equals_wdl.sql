-- Singular test: in fact_standings, games played must equal won + drawn + lost.
-- Internal-consistency check on the derived cumulative record.

select
    standing_key,
    played,
    won,
    drawn,
    lost
from {{ ref('fact_standings') }}
where played <> won + drawn + lost
