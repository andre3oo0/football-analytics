-- Staging for raw.standings: one typed row per team per matchday snapshot per
-- table type. Thin by design, so it only unpacks, renames and casts.
--
-- Raw keeps every table type the API returns (TOTAL, and mid-season HOME/AWAY),
-- and this model stays 1:1 with raw, so it doesn't drop any rows. It just
-- surfaces the choice as the is_total_standing flag: TOTAL is the real
-- league/group table, HOME/AWAY are splits we don't want at the fact grain.
-- Any actual filtering happens downstream, not here, so the decision is visible
-- and testable rather than silent.

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

    -- flag the API table type rather than filtering on it here
    (standing_type = 'TOTAL') as is_total_standing,

    -- snapshot context
    stage,
    group_name,

    -- table row, unpacked from the JSON payload
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

    _source_file,
    _loaded_at
from source
