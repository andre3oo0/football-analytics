# Orchestration

The pipeline runs in GitHub Actions, defined in
[`.github/workflows/pipeline.yml`](../.github/workflows/pipeline.yml).

## Triggers

- `schedule`: cron `0 6 * * *` (06:00 UTC daily).
- `workflow_dispatch`: a manual "Run workflow" button.

## Job steps

The job runs on `ubuntu-latest`, one job, steps in order:

1. Check out the repository.
2. Set up Python 3.11 (with pip caching).
3. `pip install -r requirements.txt`.
4. Ingest the live season: `python -m ingestion.run --refresh`.
5. `dbt build --profiles-dir .` (run models and tests together).
6. `dbt docs generate --profiles-dir .`.
7. Upload the docs (`index.html`, `manifest.json`, `catalog.json`) as an artifact.

Each step is its own process, so the DuckDB file is opened and closed cleanly
between steps and never has two writers.

## Fail loudly

`dbt build` exits non-zero if any test fails, which fails the step and turns the
job red. Ingestion also exits non-zero if any endpoint failed. There is no path
where a data-quality problem passes silently.

## Secrets

The API key is a GitHub repository secret, `FOOTBALL_DATA_API_KEY`, injected as
an environment variable on the job. It is never committed (only `.env.example`
is in git), never echoed by the code, and GitHub masks it in logs. The ingestion
code reads it from the environment via `python-dotenv` (which falls back to the
real environment variable when there is no `.env`).

## Concurrency

A `concurrency` group named `football-data-pipeline` with
`cancel-in-progress: false` ensures two scheduled runs cannot overlap. This is
the single-writer rule applied at the workflow level.

## TLS on the runner

The client calls `truststore.inject_into_ssl()`, which uses the runner's OS
trust store. `ubuntu-latest` ships the standard public CAs and has no corporate
root, so on CI this is just ordinary public-CA verification. The corporate-proxy
case only applies on the original dev machine. If the ingest step connects and
gets 200s, TLS in CI is fine. Confirmed on a real runner: the workflow has run
green on GitHub Actions.

## What CI pulls, and what a run does

CI pulls only the live current season (`--refresh`, no `--season`). It does not
re-pull the completed 2024/25 or 2025/26 backfills, because that data cannot
change and re-fetching it nightly would waste API budget.

The 2026/27 season is under way, so a scheduled run does real work: it picks up
newly finished matches, and `fact_standings` extends by a matchday as results
land. Note that CI's warehouse is built from the live season only, so its
`fact_standings` covers 2026/27 alone — the multi-season table with the full
backfilled progressions is a local artifact.

One expected quirk in the logs: the `status` `accepted_values` test is
warn-level and fires whenever the source returns dirty values in that field. A
warning there is normal. A `stage` failure would not be, and is worth
investigating.

## Setting it up on GitHub

Already wired up: the repo is pushed and the workflow runs. For reference, the
setup on a fresh remote is:

```bash
git remote add origin https://github.com/<you>/football-analytics.git
git push -u origin main
# Settings > Secrets and variables > Actions > New repository secret
#   FOOTBALL_DATA_API_KEY = <your key>
# Then Actions > football-data-pipeline > Run workflow
```

If the repo is ever recreated, the secret goes with it and must be re-added, or
the ingest step fails on a missing key.
