-- Dimension: one row per team. Sourced straight from stg_teams, which is
-- already unique on team_id (raw enforces the PK), so no dedup is needed.

select
    team_id,                   -- PK / natural key (FK target for fact_matches, fact_standings)
    team_name,
    short_name,
    tla,
    area_name,
    founded_year,
    venue,
    club_colors,
    crest_url,
    website
from {{ ref('stg_teams') }}
