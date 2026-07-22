-- Staging for raw.teams: one typed row per team. Thin by design (unpack the
-- JSON payload, rename, cast). No joins or dedup; raw.teams is already unique
-- on team_id.

with source as (
    select * from {{ source('raw', 'teams') }}
)

select
    -- natural key, carried through as-is
    team_id,
    competition_code,

    -- attributes unpacked from the JSON payload
    payload ->> '$.name'          as team_name,
    payload ->> '$.shortName'     as short_name,
    payload ->> '$.tla'           as tla,
    payload ->> '$.crest'         as crest_url,
    (payload ->> '$.founded')::integer as founded_year,
    payload ->> '$.venue'         as venue,
    payload ->> '$.clubColors'    as club_colors,
    payload ->> '$.website'       as website,
    payload ->> '$.area.name'     as area_name,

    _source_file,
    _loaded_at
from source
