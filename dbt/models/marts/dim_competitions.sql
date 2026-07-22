-- One row per competition. Comes from a seed because competition_type
-- (LEAGUE vs TOURNAMENT) is my own classification, not a raw API field, and the
-- list of competitions is small, static reference data.

select
    competition_code,          -- primary key (facts reference it)
    competition_name,
    competition_type           -- 'LEAGUE' or 'TOURNAMENT'
from {{ ref('seed_competitions') }}
