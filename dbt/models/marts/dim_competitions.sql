-- Dimension: one row per competition.
-- Sourced from a seed because competition_type (LEAGUE vs TOURNAMENT) is our
-- analytical classification, not a raw API field, and the competition list is
-- small static reference data.

select
    competition_code,          -- PK / natural key (FK target for facts)
    competition_name,
    competition_type           -- 'LEAGUE' | 'TOURNAMENT'
from {{ ref('seed_competitions') }}
