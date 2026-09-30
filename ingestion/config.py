"""Configuration for the ingestion layer.

Plain data (no logic beyond reading the seed) so the competitions, endpoints and
the rate-limit budget are all in one obvious place.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

# Paths. Repo root is the parent of the ingestion/ package.
REPO_ROOT: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = REPO_ROOT / "data"
RAW_CACHE_DIR: Path = DATA_DIR / "raw"          # cached API responses (git-ignored)
DEFAULT_DB_PATH: Path = DATA_DIR / "football.duckdb"
COMPETITIONS_SEED: Path = REPO_ROOT / "dbt" / "seeds" / "seed_competitions.csv"

# API.
BASE_URL: str = "https://api.football-data.org/v4"
API_KEY_ENV_VAR: str = "FOOTBALL_DATA_API_KEY"

# The free tier caps you at 10 requests/minute. One request every 7.5s (~8/min)
# leaves headroom for clock skew and the odd retry.
MIN_SECONDS_BETWEEN_REQUESTS: float = 7.5
MAX_RETRIES: int = 5
BACKOFF_BASE_SECONDS: float = 5.0   # base for exponential backoff on 429 / 5xx / network errors
REQUEST_TIMEOUT_SECONDS: float = 30.0


@dataclass(frozen=True)
class Competition:
    code: str              # football-data.org code, e.g. "PL"
    name: str


def load_competitions(seed_path: Path = COMPETITIONS_SEED) -> list[Competition]:
    """Read the competitions in scope from the dbt seed.

    The seed is the single source of truth, so ingestion and dim_competitions
    can't disagree about which leagues exist.
    """
    with seed_path.open(encoding="utf-8", newline="") as fh:
        return [
            Competition(row["competition_code"], row["competition_name"])
            for row in csv.DictReader(fh)
        ]


COMPETITIONS: list[Competition] = load_competitions()

# Endpoint suffixes under /competitions/{code}/...
ENDPOINTS: list[str] = ["teams", "matches", "standings"]
