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
gets 200s, TLS in CI is fine. This was validated locally by running the exact CI
command sequence against a fresh live-only warehouse (green build, empty
standings, which is the correct off-season result); a real runner has not been
exercised yet because the repo has not been pushed.

## What CI pulls, and what a run does today

CI pulls only the live current season (`--refresh`, no `--season`). It does not
re-pull the completed 2024/25 or 2025/26 backfills, because that data cannot
change and re-fetching it nightly would waste API budget.

Because the leagues are in the 2026/27 off-season, a run today ingests fixtures
with no results, builds everything, and passes its tests, but `fact_standings`
comes out empty until the season starts. That is expected and stated plainly in
the workflow comments; the same workflow produces real standings once matches
are played, with no code change.

## Setting it up on GitHub

The repo has not been pushed to a remote yet. To wire it up:

```bash
git remote add origin https://github.com/<you>/football-analytics.git
git push -u origin main
# Settings > Secrets and variables > Actions > New repository secret
#   FOOTBALL_DATA_API_KEY = <your key>
# Then Actions > football-data-pipeline > Run workflow
```
