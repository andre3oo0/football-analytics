-- Dimension: one row per competition-season. Built from the deduped
-- int_seasons. season_id is unique per competition (verified), so it is the PK.

select
    season_id,                 -- PK / natural key (FK target for facts)
    competition_code,          -- FK to dim_competitions
    season_label,              -- e.g. "2026/27" (league) or "2026" (World Cup)
    season_start_date,
    season_end_date,
    current_matchday
from {{ ref('int_seasons') }}
