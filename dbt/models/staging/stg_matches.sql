-- Staging for raw.matches: one typed row per match. Thin by design (unpack the
-- JSON payload, rename, cast), no joins or business logic.
--
-- Scores stay null for matches that haven't been played; I cast them, I don't
-- coalesce them to zero. `stage` is REGULAR_SEASON for every league match.

with source as (
    select * from {{ source('raw', 'matches') }}
)

select
    -- natural key
    match_id,
    competition_code,
    (payload ->> '$.season.id')::bigint    as season_id,

    -- season context (same across a season's matches; deduped into dim_seasons)
    (payload ->> '$.season.startDate')::date        as season_start_date,
    (payload ->> '$.season.endDate')::date          as season_end_date,
    (payload ->> '$.season.currentMatchday')::integer as season_current_matchday,

    -- scheduling / classification
    (payload ->> '$.utcDate')::timestamp   as kickoff_utc,
    payload ->> '$.status'                  as status,
    payload ->> '$.stage'                   as stage,
    payload ->> '$.group'                   as group_name,
    (payload ->> '$.matchday')::integer     as matchday,

    -- participants
    (payload ->> '$.homeTeam.id')::bigint   as home_team_id,
    payload ->> '$.homeTeam.name'           as home_team_name,
    (payload ->> '$.awayTeam.id')::bigint   as away_team_id,
    payload ->> '$.awayTeam.name'           as away_team_name,

    -- result (null until played)
    payload ->> '$.score.winner'            as winner,
    payload ->> '$.score.duration'          as duration,
    (payload ->> '$.score.fullTime.home')::integer as home_score_ft,
    (payload ->> '$.score.fullTime.away')::integer as away_score_ft,
    (payload ->> '$.score.halfTime.home')::integer as home_score_ht,
    (payload ->> '$.score.halfTime.away')::integer as away_score_ht,

    _source_file,
    _loaded_at
from source
