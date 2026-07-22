"""Rate-limited, cache-first HTTP client for football-data.org.

This module does two things I care about:

1. Stay well under the rate limit so we never get IP-banned. The free tier
   allows 10 requests/minute, so I keep a minimum gap between real network
   calls (~8/min) and back off exponentially on HTTP 429, honouring the
   server's Retry-After header when it sends one.
2. Avoid hitting the API when we don't need to. Every response is cached to
   disk as JSON, and a cached response is reused by default, so re-running
   locally costs zero API calls. Pass force_refresh=True to re-fetch.
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

    Certificate verification stays on; this just lets the pipeline run behind an
    SSL-inspecting corporate proxy, which presents a locally-trusted root CA that
    certifi doesn't know about. It's a no-op if truststore isn't installed (e.g.
    on a CI runner with normal public CAs), which is exactly what we want.
    """
    try:
        import truststore

        truststore.inject_into_ssl()
    except Exception:  # best-effort, never fatal
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
        # When the last real network call happened; 0 means never.
        self._last_request_ts: float = 0.0

    def get_competition_resource(
        self,
        competition_code: str,
        resource: str,
        *,
        season: int | None = None,
        force_refresh: bool = False,
    ) -> dict:
        """Return the JSON for /competitions/{code}/{resource}.

        season (the starting year, e.g. 2024 for 2024/25) picks a specific season
        via the API's ?season= filter, and it goes into a season-scoped cache
        filename so a historical pull never clobbers the current-season cache.
        Served from the on-disk cache unless it's missing or force_refresh is set;
        whatever we return is always also written to disk as JSON.
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

        # Write the cache before returning, so the load step reads a real file.
        cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload

    def cache_path_for(
        self, competition_code: str, resource: str, season: int | None = None
    ) -> Path:
        return self._cache_path(competition_code, resource, season)

    def _cache_path(
        self, competition_code: str, resource: str, season: int | None = None
    ) -> Path:
        suffix = f"_{season}" if season is not None else ""
        return self.cache_dir / f"{competition_code}_{resource}{suffix}.json"

    def _throttle(self) -> None:
        """Sleep just long enough to keep at least min_interval between calls."""
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

            # Any other 4xx (bad key, unknown competition, ...) is not retryable.
            resp.raise_for_status()

        raise RateLimitError(
            f"Exhausted {self.max_retries} retries against {url} (HTTP 429/5xx)."
        )

    @staticmethod
    def _retry_after_seconds(resp: requests.Response, attempt: int) -> float:
        """Use the server's Retry-After if present, otherwise exponential backoff."""
        header = resp.headers.get("Retry-After")
        if header:
            try:
                return float(header) + 1.0  # small safety margin
            except ValueError:
                pass
        return BACKOFF_BASE_SECONDS * (2 ** attempt)
