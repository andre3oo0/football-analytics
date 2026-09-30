# Data model

A Kimball-style star schema: four dimensions shared by three facts. Column
types are in [data-dictionary.md](data-dictionary.md); the reasons behind the
design are in [design-decisions.md](design-decisions.md).

![Star schema ER diagram](erd.svg)

## Dimensions

**`dim_competitions`**: one row per competition, from `seed_competitions`. Key
`competition_code`; the only attribute is `competition_name`.

**`dim_seasons`**: one row per competition-season, from `int_seasons`. Key
`season_id` (unique per competition), with `competition_code`, `season_label`
("2024/25"), start and end dates, and `current_matchday`. The last is the
highest value in any stored match payload, and goes stale once a season ends.

**`dim_teams`**: one row per team, from `stg_teams`. `team_id` is stable across
seasons, so a club that is relegated and later promoted is one row. Type 1: a
rename or new crest overwrites the old values.

**`dim_date`**: one row per calendar day from the earliest season start or
kickoff to the latest season end or kickoff (a few opening fixtures fall before
the API's season start date). Year, quarter, month, ISO weekday, weekend flag,
month start and week start.

## Facts

| Fact | Grain | Keys to dimensions |
|------|-------|--------------------|
| `fact_matches` | one row per match | `competition_code`, `season_id`, `home_team_id`, `away_team_id`, `kickoff_date` |
| `fact_team_matches` | one row per team per match | `competition_code`, `season_id`, `team_id`, `kickoff_date` (plus `match_id` to `fact_matches`) |
| `fact_standings` | one row per competition, season, team and matchday | `competition_code`, `season_id`, `team_id`, `as_of_date` |

`kickoff_date` is the UTC date of kickoff.

### fact_matches

`match_id` is a degenerate dimension: a key with no dimension table of its own.
`stage`, `group_name`, `status`, `matchday`, `kickoff_utc`, `winner` and
`duration` are descriptive attributes on the fact. The measures are the
full-time and half-time scores, `total_goals_ft`, `home_points`,
`away_points` and `has_result`. Scores are null before kickoff and carry the
live score during play; points are null until the match has a result. Nothing
is coalesced to zero.

`has_result` is true for `FINISHED` and `AWARDED`. Points (3/1/0) come from the
API's `winner` field. `dim_teams` plays two roles here, home and away.

### fact_team_matches

The same matches unpivoted: each match appears once from the home side and once
from the away side, with `team_id`, `opponent_team_id`, `is_home`,
`goals_for`, `goals_against`, `goal_difference`, `points` and `result`.
`result` (W/D/L) is computed from the scores and `points` from `winner`, so
they are independent and a test checks they agree. Unplayed fixtures are
included with null measures, so a team's full schedule is here.

### fact_standings

The league table after each matchday, computed from `fact_team_matches`
(regular-season rows with a result). Each row has cumulative `played`, `won`,
`drawn`, `lost`, `goals_for`, `goals_against`, `goal_difference`, `points`
and `position`, plus the `as_of_date` the snapshot is taken at. Points are
semi-additive: take one snapshot per team, never sum across matchdays.

## How fact_standings is built

A matchday is a fixture label. Postponed games are played weeks after their
round and a few are brought forward, so "all games labelled matchday N or
earlier" doesn't describe the table at any real moment. Each snapshot is taken
as of a date instead:

1. A matchday is *played* once most of its fixtures have a result. Snapshots
   run from matchday 1 to the latest played matchday, with no gaps, so a
   matchday axis in a BI tool never skips a value.
2. For each played matchday, take the median kickoff date of its results. The
   round's end date is the latest kickoff within 3 days of that median, which
   leaves out games played far from their round.
3. `as_of_date` is the running maximum of those end dates, so it never goes
   backwards as the matchday rises. A matchday that isn't played (a round
   postponed whole) has no end date and keeps the previous snapshot's date,
   so its table is the previous one.
4. The latest matchday's `as_of_date` is the date of the season's latest
   result, so the newest snapshot is always the current table. A game brought
   forward from a later round counts there by date.
5. Each result is assigned to exactly one snapshot: the first whose
   `as_of_date` is on or after its kickoff. A postponed game therefore counts
   in the snapshot after it is played, whatever its label.
6. Every team is crossed with every snapshot, so a team with no game in a
   window still gets a row. Window sums over that scaffold give the cumulative
   figures.
7. `position` is `rank()` by points, then goal difference, then goals scored.
   Teams level on all three share a position.

A past snapshot does not change when a postponed game is finally played; until
then the team shows a game in hand. Two unit tests in `_unit_tests.yml` pin
this down: a postponed game, and a round postponed whole alongside a game
brought forward.

A season has no snapshots until most of matchday 1 has been played.

### Incremental build

`fact_standings` is incremental with `unique_key = [competition_code,
season_id]` and `incremental_strategy = 'delete+insert'`.

- On a full build every season is derived.
- On an incremental build, a season is re-derived when either:
  - any of its `fact_team_matches` rows has a `_loaded_at` newer than the newest
    `_loaded_at` in the table, or
  - its number of results differs from the sum of `played` in its latest
    snapshot, which is how a match deleted upstream is noticed.

  Because the unique key is the season, delete+insert removes all of that
  season's old rows and inserts the new ones, so no stale matchday rows survive.

The watermark works because raw only restamps `_loaded_at` when a payload
changes. The table's `_loaded_at` is the latest change among the season's
matches. CI runs a second, incremental build on every pull request.

## Staging and intermediate

- `stg_teams`, `stg_matches`, `stg_standings`: 1:1 typed views over raw.
  `stg_matches` maps a kickoff timestamp that the API sometimes puts in
  `status` to `SCHEDULED`, keeps the original as `status_raw`, and adds
  `kickoff_date`. `stg_standings` keeps every table type and flags TOTAL with
  `is_total_standing`.
- `int_seasons`: one row per competition-season from the season object repeated
  on every match. Start and end dates use `any_value` (a test checks they agree
  across the season); `current_matchday` is the highest value seen.
- `int_matches`: adds `has_result`, `total_goals_ft` and the per-side points.
