# Orchestration

Two GitHub Actions workflows in `.github/workflows/`.

| Workflow | Runs on | Needs the API key | Purpose |
|----------|---------|-------------------|---------|
| `ci.yml` | every pull request and push to `main` | no | lint, tests, a full dbt build on the fixture season |
| `pipeline.yml` | 02:00 SAST nightly via an external trigger, a fallback schedule, and manual dispatch | yes | the real pipeline on live data |

Both run on `ubuntu-latest` with Python 3.11 and have read-only repository
permissions.

## ci.yml

Two jobs, run in parallel. A newer push to the same branch cancels a running
CI job.

**python**: `pip install -r requirements-dev.txt`, then `ruff check .` and
`pytest`.

**dbt**:

1. `pip install -r requirements.txt`.
2. Load the fixture season with no API calls:
   `python -m ingestion.run --cache-dir tests/fixtures/raw --season 2024 --competitions PL`.
3. `dbt build --profiles-dir .`: seed, models, unit tests and data tests.
4. `dbt build --profiles-dir . --select fact_standings+` again, which runs
   `fact_standings` down its incremental branch against the table the first
   build created.
5. Regenerate the diagrams with `python docs/generate_diagrams.py` and run
   `git diff --exit-code` on `docs/erd.svg` and `docs/lineage_dag.svg`. A change
   to the DAG or a foreign key without updated diagrams fails here.

## pipeline.yml

A small `decide` job runs first. For a scheduled (fallback) run it checks
whether a run created since 23:50 UTC has already succeeded and, if so, skips
the rest (see [Schedule](#schedule)). Manual and API-dispatched runs always go
ahead. It needs `actions: read` to list runs; nothing else has more than
`contents: read`.

Then `run-pipeline`, steps in order:

1. Check out, set up Python, `pip install -r requirements.txt`.
2. **Restore the warehouse.** `actions/cache/restore` restores
   `data/football.duckdb` and `data/raw/*.json` from the newest cache entry
   whose key starts with `warehouse-`.
3. **Bootstrap, only if nothing was restored.** If there is no
   `data/football.duckdb`, ingest the completed seasons:
   `python -m ingestion.run --season 2024` and `--season 2025`.
4. **Ingest the live season**: `python -m ingestion.run --refresh`.
5. `dbt build --profiles-dir .`.
6. `dbt docs generate --profiles-dir .`.
7. `python export_marts.py --out exports`.
8. Print the last five rows of `raw._load_runs`.
9. **Save the warehouse** to the cache under `warehouse-<run_id>`.
10. Upload `exports/*.parquet` as the `marts-parquet` artifact (kept 14 days)
    and the dbt docs (`index.html`, `manifest.json`, `catalog.json`,
    `run_results.json`) as `dbt-docs`. The docs are uploaded even when an
    earlier step failed.

Any failing step stops the job: an ingestion failure (exit 1), a failing dbt
test, a contract violation. The save step is only reached when everything before
it succeeded, so a failed run never replaces the last good warehouse in the
cache. The next run starts from that one.

### Schedule

The nightly run should start at 02:00 SAST, which is 00:00 UTC all year
(South Africa is UTC+2 with no daylight saving). That time is chosen so no
match is in play: the latest European kickoffs are around 21:00 CET (20:00 UTC
in winter) and finish about two hours later. A run during a live game would
load it as IN_PLAY, and the reconciliation test could fail if the standings
endpoint already counted it.

GitHub's own `schedule` trigger can't hold that time. It is best effort:
runs are delayed under load, most of all at the top of the hour, and for this
repository they typically start four to seven hours late. So the run is started
from outside GitHub:

- **Primary: an external cron service** calls the `workflow_dispatch` API at
  02:00 SAST. Dispatched runs start within seconds. Setup is below.
- **Fallback: the `schedule` entry** (`0 0 * * *`). If the external trigger
  didn't fire or its run failed, this run does the work, just late. If
  tonight's run already succeeded, the `decide` job skips it, so the data isn't
  pulled twice.

If a run fails, the cache isn't updated, so no state is lost, and the next run
picks up where the last good one left off.

### Setting up the external trigger

Any cron service that can send an HTTPS POST with headers works. These steps
use [cron-job.org](https://cron-job.org) (free).

1. **Create a fine-grained personal access token** on GitHub: Settings >
   Developer settings > Personal access tokens > Fine-grained tokens >
   Generate new token.
   - Repository access: *Only select repositories*, this repository only.
   - Permissions: *Actions: Read and write* (Metadata: Read-only is added
     automatically). Nothing else.
   - Expiration: the longest you're comfortable with. Put a reminder in your
     calendar to renew it; an expired token makes the call fail with 401 and
     the fallback schedule takes over.
2. **Create the cron job** on cron-job.org:
   - URL: `https://api.github.com/repos/<owner>/<repo>/actions/workflows/pipeline.yml/dispatches`
   - Schedule: every day at 02:00, time zone *Africa/Johannesburg*.
   - Advanced > Request method: `POST`.
   - Headers:
     - `Authorization: Bearer <token>`
     - `Accept: application/vnd.github+json`
     - `X-GitHub-Api-Version: 2022-11-28`
     - `Content-Type: application/json`
   - Request body: `{"ref":"main"}`
   - Turn on failure notifications, so a failed call emails you.
3. **Test it** with the service's "Test run" button. GitHub answers
   `204 No Content`, and a new `workflow_dispatch` run appears under Actions >
   football-data-pipeline within a few seconds.

The token only allows starting and reading workflow runs on this repository.
Keep it in the cron service only; it doesn't go in the repository.

### Cache eviction

GitHub evicts cache entries not used for 7 days, and a repository's cache has a
size limit. If the entry is gone, step 3 re-pulls the completed seasons from
the API before the live ingest, which costs 30 extra requests. Nothing else is
lost: raw is rebuilt from the API and everything downstream from raw.

### Concurrency

The concurrency group `football-data-pipeline` with `cancel-in-progress: false`
queues a second run behind the first, so two runs never write the same
warehouse or race on the cache.

## Secrets

The API key is the repository secret `FOOTBALL_DATA_API_KEY`, passed to the
pipeline job as an environment variable. It is never committed (only
`.env.example` is in git) and GitHub masks it in logs. `ci.yml` doesn't use it.

## Dependencies and pinning

Every action is pinned to a commit SHA, with the version in a comment.
Dependabot (`.github/dependabot.yml`) opens monthly pull requests for GitHub
Actions and for the pip requirements, and CI runs on each one.

## Setting it up on a fork

1. Push the repository to GitHub.
2. Add the secret: Settings > Secrets and variables > Actions > New repository
   secret, `FOOTBALL_DATA_API_KEY`.
3. Run Actions > football-data-pipeline > Run workflow once. With an empty
   cache, it bootstraps the completed seasons.
4. Set up the external trigger ([above](#setting-up-the-external-trigger)).
   Without it, the fallback schedule still runs every night, just hours late.

`ci.yml` needs no setup.
