-- League table after each matchday: one row per (competition, season, team,
-- matchday), derived from match results rather than the standings endpoint
-- (which only ever returns the current table).
--
-- A matchday is a fixture label, not a point in time: postponed games are
-- played weeks later, and a few are brought forward. So each snapshot is taken
-- AS OF A DATE and counts every result played by then, whatever its label:
--
--   played round  = a matchday where most fixtures have a result. Snapshots
--                   run from matchday 1 to the latest played round, with no
--                   gaps.
--   as_of_date(N) = the last day of matchday N's on-schedule games, where
--                   on-schedule means within 3 days of the round's median
--                   kickoff date; forced non-decreasing across matchdays. A
--                   matchday that isn't a played round keeps the previous date.
--   latest N      = the date of the season's latest result, so the newest
--                   snapshot is always the current table.
--
-- The snapshot for a past matchday therefore never changes when a postponed
-- game is finally played. The team simply shows a game in hand until then.
--
-- Position ties are shared (rank): points, then goal difference, then goals
-- for. Head-to-head and other league-specific tie-breaks are not modelled.
--
-- Incremental: when any match of a season changes (raw _loaded_at only moves
-- when a payload changes), the whole season is re-derived and its rows are
-- replaced. unique_key is the season, so delete+insert drops the season's old
-- rows, including any that no longer exist.

{{ config(
    materialized = 'incremental',
    unique_key   = ['competition_code', 'season_id'],
    incremental_strategy = 'delete+insert',
    on_schema_change = 'fail'
) }}

{% if is_incremental() %}
with changed_seasons as (
    select competition_code, season_id
    from {{ ref('fact_team_matches') }}
    where _loaded_at > (select coalesce(max(_loaded_at), timestamp '1900-01-01') from {{ this }})

    union

    -- A match deleted upstream moves no _loaded_at, but it changes how many
    -- results the season has. The latest snapshot's played column adds up to
    -- exactly that number, so compare the two.
    select competition_code, season_id
    from (
        select competition_code, season_id, count(*) filter (where has_result) as n_results
        from {{ ref('fact_team_matches') }}
        where stage = 'REGULAR_SEASON'
        group by competition_code, season_id
    ) now
    full outer join (
        select competition_code, season_id, sum(played) as n_results
        from (
            select * from {{ this }}
            qualify matchday = max(matchday) over (partition by competition_code, season_id)
        )
        group by competition_code, season_id
    ) built using (competition_code, season_id)
    where coalesce(now.n_results, 0) <> coalesce(built.n_results, 0)
),

team_matches as (
    select m.*
    from {{ ref('fact_team_matches') }} m
    join changed_seasons using (competition_code, season_id)
    where m.stage = 'REGULAR_SEASON'
),
{% else %}
with team_matches as (
    select * from {{ ref('fact_team_matches') }}
    where stage = 'REGULAR_SEASON'
),
{% endif %}

season_loaded_at as (
    select competition_code, season_id, max(_loaded_at) as _loaded_at
    from team_matches
    group by competition_code, season_id
),

results as (
    select * from team_matches where has_result
),

-- how many fixtures each matchday has, and how many of them have a result
round_progress as (
    select competition_code, season_id, matchday,
           count(distinct match_id)                           as n_fixtures,
           count(distinct match_id) filter (where has_result) as n_results
    from team_matches
    group by competition_code, season_id, matchday
),

round_medians as (
    select competition_code, season_id, matchday,
           quantile_disc(kickoff_date, 0.5) as median_date
    from results
    group by competition_code, season_id, matchday
),

round_ends as (
    select r.competition_code, r.season_id, r.matchday,
           max(r.kickoff_date) as round_end_date
    from results r
    join round_medians m using (competition_code, season_id, matchday)
    where abs(date_diff('day', m.median_date, r.kickoff_date)) <= 3
    group by r.competition_code, r.season_id, r.matchday
),

-- A matchday is "played" once most of its fixtures have a result. The latest
-- played matchday ends the series, and every label from 1 up to it gets a
-- snapshot, so there are no gaps. A matchday that isn't played yet (a round
-- postponed as a whole, or one game brought forward from a later round) has no
-- date of its own and carries the previous snapshot's date forward.
latest_round as (
    select competition_code, season_id, max(matchday) as latest_matchday
    from round_progress
    where n_results * 2 > n_fixtures
    group by competition_code, season_id
),

labels as (
    select
        p.competition_code,
        p.season_id,
        p.matchday,
        case when p.n_results * 2 > p.n_fixtures then e.round_end_date end as round_end_date,
        p.matchday = l.latest_matchday                                        as is_latest
    from round_progress p
    join latest_round l using (competition_code, season_id)
    left join round_ends e using (competition_code, season_id, matchday)
    where p.matchday <= l.latest_matchday
),

snapshots as (
    select
        competition_code,
        season_id,
        matchday,
        is_latest,
        max(round_end_date) over (partition by competition_code, season_id order by matchday
                                  rows between unbounded preceding and current row) as as_of_date
    from labels
),

result_dates as (
    select competition_code, season_id,
           min(kickoff_date) as first_result_date,
           max(kickoff_date) as last_result_date
    from results
    group by competition_code, season_id
),

snapshot_windows as (
    select
        s.competition_code,
        s.season_id,
        s.matchday,
        case
            when s.is_latest then d.last_result_date
            -- only when the opening matchdays aren't played yet: nothing counts
            else coalesce(s.as_of_date, d.first_result_date - 1)
        end as as_of_date
    from snapshots s
    join result_dates d using (competition_code, season_id)
),

-- Each result lands in exactly one snapshot: the first whose as_of_date is on
-- or after its kickoff. Later snapshots pick it up through the running sum.
bucketed as (
    select w.matchday as snapshot_matchday, r.*
    from results r
    join (
        select *,
               lag(as_of_date) over (partition by competition_code, season_id
                                     order by matchday) as prev_as_of_date
        from snapshot_windows
    ) w
      on  w.competition_code = r.competition_code
      and w.season_id        = r.season_id
      and r.kickoff_date    <= w.as_of_date
      and (w.prev_as_of_date is null or r.kickoff_date > w.prev_as_of_date)
),

per_snapshot as (
    select
        competition_code, season_id, team_id, snapshot_matchday as matchday,
        count(*)                              as played,
        count(*) filter (where result = 'W')  as won,
        count(*) filter (where result = 'D')  as drawn,
        count(*) filter (where result = 'L')  as lost,
        sum(goals_for)                        as goals_for,
        sum(goals_against)                    as goals_against,
        sum(points)                           as points
    from bucketed
    group by competition_code, season_id, team_id, snapshot_matchday
),

-- every team crossed with every snapshot, so a team with no game in a window
-- still gets a row
scaffold as (
    select t.competition_code, t.season_id, t.team_id, w.matchday, w.as_of_date
    from (select distinct competition_code, season_id, team_id from results) t
    join snapshot_windows w using (competition_code, season_id)
),

cumulative as (
    select
        s.competition_code,
        s.season_id,
        s.team_id,
        s.matchday,
        s.as_of_date,
        sum(coalesce(p.played, 0))        over team_w as played,
        sum(coalesce(p.won, 0))           over team_w as won,
        sum(coalesce(p.drawn, 0))         over team_w as drawn,
        sum(coalesce(p.lost, 0))          over team_w as lost,
        sum(coalesce(p.goals_for, 0))     over team_w as goals_for,
        sum(coalesce(p.goals_against, 0)) over team_w as goals_against,
        sum(coalesce(p.points, 0))        over team_w as points
    from scaffold s
    left join per_snapshot p using (competition_code, season_id, team_id, matchday)
    window team_w as (partition by s.competition_code, s.season_id, s.team_id
                      order by s.matchday
                      rows between unbounded preceding and current row)
)

select
    c.competition_code,
    c.season_id,
    c.team_id,
    c.matchday,
    c.as_of_date,
    c.played::integer                         as played,
    c.won::integer                            as won,
    c.drawn::integer                          as drawn,
    c.lost::integer                           as lost,
    c.goals_for::integer                      as goals_for,
    c.goals_against::integer                  as goals_against,
    (c.goals_for - c.goals_against)::integer  as goal_difference,
    c.points::integer                         as points,
    rank() over (
        partition by c.competition_code, c.season_id, c.matchday
        order by c.points desc, c.goals_for - c.goals_against desc, c.goals_for desc
    )::integer                                as position,
    l._loaded_at
from cumulative c
join season_loaded_at l using (competition_code, season_id)
