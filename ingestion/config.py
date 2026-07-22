"""Configuration for the ingestion layer.

I keep this as plain data (no logic) so the competitions, endpoints and the
rate-limit budget are all in one obvious place.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Paths. Repo root is the parent of the ingestion/ package.
REPO_ROOT: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = REPO_ROOT / "data"
RAW_CACHE_DIR: Path = DATA_DIR / "raw"          # cached API responses (git-ignored)
DEFAULT_DB_PATH: Path = DATA_DIR / "football.duckdb"

# API.
BASE_URL: str = "https://api.football-data.org/v4"
API_KEY_ENV_VAR: str = "FOOTBALL_DATA_API_KEY"

# The free tier caps you at 10 requests/minute. I aim for ~8/min (one request
# every 7.5s) to leave headroom, so getting IP-banned isn't really possible.
MIN_SECONDS_BETWEEN_REQUESTS: float = 7.5
MAX_RETRIES: int = 5
BACKOFF_BASE_SECONDS: float = 5.0   # base for exponential backoff on 429 / 5xx


@dataclass(frozen=True)
class Competition:
    code: str              # football-data.org code, e.g. "PL"
    name: str
    competition_type: str  # "LEAGUE" or "TOURNAMENT"


# The five leagues are what drive the incremental and scheduling story. The
# World Cup is the headline competition but its data is mostly static.
COMPETITIONS: list[Competition] = [
    Competition("PL", "Premier League", "LEAGUE"),
    Competition("PD", "La Liga", "LEAGUE"),
    Competition("BL1", "Bundesliga", "LEAGUE"),
    Competition("SA", "Serie A", "LEAGUE"),
    Competition("FL1", "Ligue 1", "LEAGUE"),
    Competition("WC", "FIFA World Cup 2026", "TOURNAMENT"),
]

# Endpoint suffixes under /competitions/{code}/...
ENDPOINTS: list[str] = ["teams", "matches", "standings"]
