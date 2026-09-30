-- One row per competition, from the seed. The seed is also what ingestion
-- reads to decide which competitions to pull, so the two can't drift apart.

select
    competition_code,
    competition_name
from {{ ref('seed_competitions') }}
