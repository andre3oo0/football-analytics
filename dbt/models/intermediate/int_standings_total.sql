-- Intermediate: apply the TOTAL-only decision.
--
-- THIS is where the TOTAL vs HOME/AWAY choice is enforced — a documented
-- modelling decision, not something hidden at ingest or in staging. Raw keeps
-- every table type; staging exposed the `is_total_standing` flag; here we
-- filter to the real league/group table that feeds fact_standings (one row per
-- team per matchday snapshot). If the source ever returns HOME/AWAY, they are
-- deliberately excluded here and this single WHERE is the auditable reason.

select
    competition_code,
    season_id,
    team_id,
    matchday,
    stage,
    group_name,
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
    team_name,
    _loaded_at
from {{ ref('stg_standings') }}
where is_total_standing
