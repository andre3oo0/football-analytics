"""Rate-limited, cache-first HTTP client for football-data.org.

Two guarantees this module exists to provide:

1. **Never get IP-banned.** The free tier allows 10 requests/minute. We enforce
   a minimum gap between *real* network calls (~8/min) and back off
   exponentially on HTTP 429, honouring the server's Retry-After when given.

2. **Never re-hit the API needlessly.** Every response is cached to disk as
   JSON. By default a cached response is reused, so development re-runs cost
   zero API calls. Pass ``force_refresh=True`` to re-fetch live data.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from .config import (
    BACKOFF_BASE_SECONDS,
    BASE_URL,
    MAX_RETRIES,
    MIN_SECONDS_BETWEEN_REQUESTS,
)


def _enable_os_trust_store() -> None:
    """Verify TLS against the OS certificate store instead of certifi's bundle.

    This keeps certificate verification fully ON while allowing the pipeline to
    run behind SSL-inspecting corporate proxies, which present a locally-trusted
    root CA that certifi does not know about. No-op if ``truststore`` is not
    installed or injection fails.
    """
    try:
        import truststore

        truststore.inject_into_ssl()
    except Exception:  # pragma: no cover - best-effort, never fatal
        pass


class RateLimitError(RuntimeError):
    """Raised when we exhaust retries against HTTP 429."""


class FootballDataClient:
    def __init__(
        self,
        api_key: str | None,
        cache_dir: Path,
        *,
        min_interval: float = MIN_SECONDS_BETWEEN_REQUESTS,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        _enable_os_trust_store()
        self.api_key = api_key
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval
        self.max_retries = max_retries
        self._session = requests.Session()
        if api_key:
            self._session.headers.update({"X-Auth-Token": api_key})
        # Timestamp of the last *real* network call; 0 means "never".
        self._last_request_ts: float = 0.0

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def get_competition_resource(
        self,
        competition_code: str,
        resource: str,
        *,
        season: int | None = None,
        force_refresh: bool = False,
    ) -> dict:
        """Return the JSON for /competitions/{code}/{resource}.

        ``season`` (the starting year, e.g. 2024 for 2024/25) selects a specific
        season via the API's ?season= filter and is kept in a season-scoped cache
        filename, so a historical season never overwrites the current-season
        cache. Served from the on-disk cache unless it is missing or
        force_refresh is set. Whatever we return is always also on disk as JSON.
        """
        cache_path = self._cache_path(competition_code, resource, season)

        if cache_path.exists() and not force_refresh:
            with cache_path.open(encoding="utf-8") as fh:
                return json.load(fh)

        if not self.api_key:
            raise RuntimeError(
                f"No cached response at {cache_path} and no API key set "
                f"(env var not provided). Cannot fetch {competition_code}/{resource}."
            )

        url = f"{BASE_URL}/competitions/{competition_code}/{resource}"
        if season is not None:
            url += f"?season={season}"
        payload = self._request_with_backoff(url)

        # Cache BEFORE returning so the load step reads a persisted artifact.
        cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload

    def cache_path_for(
        self, competition_code: str, resource: str, season: int | None = None
    ) -> Path:
        return self._cache_path(competition_code, resource, season)

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _cache_path(
        self, competition_code: str, resource: str, season: int | None = None
    ) -> Path:
        suffix = f"_{season}" if season is not None else ""
        return self.cache_dir / f"{competition_code}_{resource}{suffix}.json"

    def _throttle(self) -> None:
        """Sleep just long enough to keep >= min_interval between real calls."""
        elapsed = time.monotonic() - self._last_request_ts
        wait = self.min_interval - elapsed
        if self._last_request_ts and wait > 0:
            time.sleep(wait)

    def _request_with_backoff(self, url: str) -> dict:
        for attempt in range(self.max_retries):
            self._throttle()
            self._last_request_ts = time.monotonic()
            resp = self._session.get(url, timeout=30)

            if resp.status_code == 200:
                return resp.json()

            if resp.status_code == 429:
                wait = self._retry_after_seconds(resp, attempt)
                print(
                    f"  [429] rate-limited on {url}; backing off {wait:.1f}s "
                    f"(attempt {attempt + 1}/{self.max_retries})"
                )
                time.sleep(wait)
                continue

            if 500 <= resp.status_code < 600:
                wait = BACKOFF_BASE_SECONDS * (2 ** attempt)
                print(
                    f"  [{resp.status_code}] server error on {url}; retrying in "
                    f"{wait:.1f}s (attempt {attempt + 1}/{self.max_retries})"
                )
                time.sleep(wait)
                continue

            # 4xx other than 429 (bad key, unknown competition, ...) — no retry.
            resp.raise_for_status()

        raise RateLimitError(
            f"Exhausted {self.max_retries} retries against {url} (HTTP 429/5xx)."
        )

    @staticmethod
    def _retry_after_seconds(resp: requests.Response, attempt: int) -> float:
        """Prefer the server's Retry-After header; else exponential backoff."""
        header = resp.headers.get("Retry-After")
        if header:
            try:
                return float(header) + 1.0  # +1s safety margin
            except ValueError:
                pass
        return BACKOFF_BASE_SECONDS * (2 ** attempt)
