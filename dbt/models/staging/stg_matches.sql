-- Staging for raw.matches: one typed row per match. Unpack the JSON payload,
-- rename, cast, and normalise status. No joins or business logic.
--
-- Scores stay null for matches that haven't been played; they're cast, not
-- coalesced to zero.

with source as (
    select * from {{ source('raw', 'matches') }}
),

typed as (
    select
        match_id,
        competition_code,
        (payload ->> '$.season.id')::bigint               as season_id,

        (payload ->> '$.season.startDate')::date          as season_start_date,
        (payload ->> '$.season.endDate')::date            as season_end_date,
        (payload ->> '$.season.currentMatchday')::integer as season_current_matchday,

        (payload ->> '$.utcDate')::timestamp              as kickoff_utc,
        payload ->> '$.status'                            as status_raw,
        payload ->> '$.stage'                             as stage,
        payload ->> '$.group'                             as group_name,
        (payload ->> '$.matchday')::integer               as matchday,

        (payload ->> '$.homeTeam.id')::bigint             as home_team_id,
        payload ->> '$.homeTeam.name'                     as home_team_name,
        (payload ->> '$.awayTeam.id')::bigint             as away_team_id,
        payload ->> '$.awayTeam.name'                     as away_team_name,

        payload ->> '$.score.winner'                      as winner,
        payload ->> '$.score.duration'                    as duration,
        (payload ->> '$.score.fullTime.home')::integer    as home_score_ft,
        (payload ->> '$.score.fullTime.away')::integer    as away_score_ft,
        (payload ->> '$.score.halfTime.home')::integer    as home_score_ht,
        (payload ->> '$.score.halfTime.away')::integer    as away_score_ht,

        _source_file,
        _loaded_at
    from source
)

select
    * exclude (status_raw),
    -- The free tier sometimes puts the kickoff timestamp in `status` for a
    -- future fixture. Those are scheduled matches, so map them to SCHEDULED.
    -- Any other unexpected value passes through and fails the accepted_values
    -- test, so a genuinely new status is noticed.
    case
        when regexp_matches(status_raw, '^\d{4}-\d{2}-\d{2}') then 'SCHEDULED'
        else status_raw
    end                                                   as status,
    status_raw,
    kickoff_utc::date                                     as kickoff_date
from typed
