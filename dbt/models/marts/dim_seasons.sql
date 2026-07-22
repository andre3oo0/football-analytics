-- One row per competition-season, from the deduped int_seasons. season_id is
-- unique per competition, so it works as the primary key.

select
    season_id,                 -- primary key (facts reference it)
    competition_code,          -- FK to dim_competitions
    season_label,              -- e.g. "2026/27" for a league, "2026" for the WC
    season_start_date,
    season_end_date,
    current_matchday
from {{ ref('int_seasons') }}
