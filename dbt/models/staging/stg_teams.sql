-- Staging: raw.teams -> one typed row per team.
-- THIN by design: unpack the JSON payload, rename, cast. Nothing else.
-- No joins, no dedup, no filtering (raw.teams is already unique on team_id).

with source as (
    select * from {{ source('raw', 'teams') }}
)

select
    -- natural key (already typed in raw, carried through 1:1)
    team_id,
    competition_code,

    -- attributes unpacked from the raw JSON payload
    payload ->> '$.name'          as team_name,
    payload ->> '$.shortName'     as short_name,
    payload ->> '$.tla'           as tla,
    payload ->> '$.crest'         as crest_url,
    (payload ->> '$.founded')::integer as founded_year,
    payload ->> '$.venue'         as venue,
    payload ->> '$.clubColors'    as club_colors,
    payload ->> '$.website'       as website,
    payload ->> '$.area.name'     as area_name,

    -- ingestion metadata
    _source_file,
    _loaded_at
from source
