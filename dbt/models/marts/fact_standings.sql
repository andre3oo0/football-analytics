-- Fact: one row per team per matchday snapshot (INCREMENTAL).
--
-- Why incremental
-- ---------------
-- Standings are a time series: as a season progresses the source only ever
-- returns the CURRENT matchday's table, so history is built up over many
-- pipeline runs. We must accumulate matchday snapshots without re-reading the
-- whole warehouse each run, and — critically — a re-fetch of a matchday that is
-- still in progress must UPDATE that (team, matchday) row in place, never add a
-- duplicate.
--
-- unique_key           = standing_key  (competition|season|team|matchday)
-- incremental_strategy = delete+insert
--
-- Why delete+insert (not append, not merge)
-- ------------------------------------------
--   * append would duplicate a re-fetched matchday — wrong.
--   * delete+insert deletes every target row whose standing_key is in the
--     incoming batch, then inserts the batch. So a re-fetched (team, matchday)
--     snapshot with changed numbers REPLACES the old row (update-in-place),
--     while a brand-new matchday is simply inserted. Exactly the semantics we
--     want, and the simplest, best-supported strategy on dbt-duckdb.
--   * merge would work too but adds column-by-column update SQL for no benefit
--     here — delete+insert on a single surrogate key is clearer.
--
-- First run vs subsequent runs
-- ----------------------------
--   * First run (or --full-refresh): the table does not exist, is_incremental()
--     is false, so the whole SELECT builds the table from all snapshots in raw.
--   * Later runs: is_incremental() is true, so we only pull snapshots newer than
--     what we already stored (_loaded_at watermark). Every raw upsert bumps
--     _loaded_at, so any re-fetched matchday is picked up and replaced.

{{ config(
    materialized = 'incremental',
    unique_key   = 'standing_key',
    incremental_strategy = 'delete+insert'
) }}

with total as (
    select * from {{ ref('int_standings_total') }}
)

select
    -- surrogate grain key (also the incremental unique_key)
    concat_ws('|', competition_code, cast(season_id as varchar),
                    cast(team_id as varchar), cast(matchday as varchar)) as standing_key,

    -- foreign keys / grain
    competition_code,          -- -> dim_competitions
    season_id,                 -- -> dim_seasons
    team_id,                   -- -> dim_teams
    matchday,

    -- snapshot context
    stage,
    group_name,

    -- measures
    position,
    played_games,
    won,
    draw,
    lost,
    points,
    goals_for,
    goals_against,
    goal_difference,
    recent_form,

    -- watermark used by the incremental filter
    _loaded_at
from total

{% if is_incremental() %}
    -- only snapshots loaded since the last build; delete+insert then replaces
    -- any matchday that was re-fetched with updated figures.
    where _loaded_at > (select coalesce(max(_loaded_at), '1900-01-01'::timestamp) from {{ this }})
{% endif %}
