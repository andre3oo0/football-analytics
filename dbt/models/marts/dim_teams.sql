-- One row per team, straight from stg_teams. raw.teams already enforces the
-- team_id primary key, so there's nothing to dedup.

select
    team_id,                   -- primary key (facts reference it)
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
