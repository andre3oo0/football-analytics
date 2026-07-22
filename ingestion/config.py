"""Static configuration for the ingestion layer.

Kept as plain data (no logic) so the set of competitions/endpoints and the
rate-limit budget are obvious and easy to defend.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
# Repo root = parent of the ingestion/ package directory.
REPO_ROOT: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = REPO_ROOT / "data"
RAW_CACHE_DIR: Path = DATA_DIR / "raw"          # cached API responses (git-ignored)
DEFAULT_DB_PATH: Path = DATA_DIR / "football.duckdb"

# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
BASE_URL: str = "https://api.football-data.org/v4"
API_KEY_ENV_VAR: str = "FOOTBALL_DATA_API_KEY"

# Free tier hard limit is 10 requests/minute. We target ~8/min (one request
# every 7.5s) to leave headroom so an IP ban is impossible by design.
MIN_SECONDS_BETWEEN_REQUESTS: float = 7.5
MAX_RETRIES: int = 5
BACKOFF_BASE_SECONDS: float = 5.0   # exponential backoff base on HTTP 429 / 5xx


# --------------------------------------------------------------------------- #
# Competitions & endpoints
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Competition:
    code: str            # football-data.org competition code, e.g. "PL"
    name: str
    competition_type: str  # "LEAGUE" | "TOURNAMENT"


# Live leagues drive the incremental + orchestration story.
# The World Cup is the report headline but is (mostly) static data.
COMPETITIONS: list[Competition] = [
    Competition("PL", "Premier League", "LEAGUE"),
    Competition("PD", "La Liga", "LEAGUE"),
    Competition("BL1", "Bundesliga", "LEAGUE"),
    Competition("SA", "Serie A", "LEAGUE"),
    Competition("FL1", "Ligue 1", "LEAGUE"),
    Competition("WC", "FIFA World Cup 2026", "TOURNAMENT"),
]

# Endpoint suffixes under /competitions/{code}/... .
# Order matters only cosmetically; teams first reads naturally.
ENDPOINTS: list[str] = ["teams", "matches", "standings"]
