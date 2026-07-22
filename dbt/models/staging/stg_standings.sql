-- Staging: raw.standings -> one typed row per team per matchday snapshot per
-- table type. THIN by design: unpack, rename, cast. Nothing else.
--
-- The TOTAL vs HOME/AWAY decision, made explicit
-- -------------------------------------------------
-- Raw preserves every table type the API returns (TOTAL, and mid-season
-- HOME/AWAY). Staging stays strictly 1:1 with raw, so it does NOT filter any
-- rows away. Instead it SURFACES the decision as the `is_total_standing` flag:
--   * TOTAL is the real league / group table used for fact_standings.
--   * HOME/AWAY are split tables we do not want at the fact grain.
-- The actual FILTER (keep only TOTAL) is applied downstream in the
-- intermediate layer (Phase 4), where dropping rows is a legitimate modelling
-- step. That keeps the choice documented and testable, never silent, and keeps
-- staging honest to raw.

with source as (
    select * from {{ source('raw', 'standings') }}
)

select
    -- natural key
    competition_code,
    season_id,
    team_id,
    matchday,
    standing_type,

    -- explicit, documented classification of the API table type
    (standing_type = 'TOTAL') as is_total_standing,

    -- snapshot context
    stage,
    group_name,

    -- table row, unpacked from the raw JSON payload
    (payload ->> '$.position')::integer        as position,
    (payload ->> '$.playedGames')::integer     as played_games,
    (payload ->> '$.won')::integer             as won,
    (payload ->> '$.draw')::integer            as draw,
    (payload ->> '$.lost')::integer            as lost,
    (payload ->> '$.points')::integer          as points,
    (payload ->> '$.goalsFor')::integer        as goals_for,
    (payload ->> '$.goalsAgainst')::integer    as goals_against,
    (payload ->> '$.goalDifference')::integer  as goal_difference,
    payload ->> '$.form'                        as recent_form,
    payload ->> '$.team.name'                   as team_name,

    -- ingestion metadata
    _source_file,
    _loaded_at
from source
