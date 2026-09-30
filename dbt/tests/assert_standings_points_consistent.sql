-- points must equal 3*won + drawn. Points are summed from the API's `winner`
-- field and won/drawn from the scores (see fact_team_matches), so this checks
-- two independent sources agree at every snapshot. It would also fail on a
-- points deduction, which isn't modelled.

select competition_code, season_id, team_id, matchday, points, won, drawn
from {{ ref('fact_standings') }}
where points <> won * 3 + drawn
