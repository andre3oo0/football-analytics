# Orchestration

Two GitHub Actions workflows in `.github/workflows/`.

| Workflow | Runs on | Needs the API key | Purpose |
|----------|---------|-------------------|---------|
| `ci.yml` | every pull request and push to `main` | no | lint, tests, a full dbt build on the fixture season |
| `pipeline.yml` | 06:00 UTC daily and manual dispatch | yes | the real pipeline on live data |

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

One job, steps in order:

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

`ci.yml` needs no setup.
