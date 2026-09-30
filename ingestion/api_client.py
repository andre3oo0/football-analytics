"""Rate-limited, cache-first HTTP client for football-data.org.

1. Stay under the rate limit. The free tier allows 10 requests/minute, so the
   client keeps a minimum gap between real network calls (~8/min). It retries
   HTTP 429 (honouring Retry-After), 5xx, connection errors and timeouts with
   exponential backoff plus jitter.
2. Avoid hitting the API when it isn't needed. Every response is cached to disk
   as JSON and reused by default, so re-running locally costs zero API calls.
   Pass force_refresh=True to re-fetch.

A response is validated before it is cached, and the cache file is written
atomically, so a bad body or a crash mid-write never leaves a file that
cache-first mode would then serve forever.
"""

from __future__ import annotations

import json
import logging
import os
import random
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

import requests

from .config import (
    BACKOFF_BASE_SECONDS,
    BASE_URL,
    MAX_RETRIES,
    MIN_SECONDS_BETWEEN_REQUESTS,
    REQUEST_TIMEOUT_SECONDS,
)

log = logging.getLogger(__name__)


def _enable_os_trust_store() -> None:
    """Verify TLS against the OS certificate store instead of certifi's bundle.

    Verification stays on; this lets the pipeline run behind a proxy whose root
    CA is trusted by the OS but not by certifi. Without truststore installed it
    does nothing, which is the normal case on a CI runner.
    """
    try:
        import truststore
    except ImportError:
        log.debug("truststore not installed; using certifi's CA bundle")
        return
    try:
        truststore.inject_into_ssl()
    except Exception as exc:  # noqa: BLE001 - never fatal, but say so
        log.warning("truststore.inject_into_ssl() failed, falling back to certifi: %s", exc)


class RateLimitError(RuntimeError):
    """Raised when retries are exhausted (429, 5xx or network errors)."""


class ResourceNotFound(RuntimeError):
    """Raised on HTTP 404. The resource genuinely doesn't exist, which is a
    legitimate state for some endpoints (e.g. no standings table for a season).
    Callers can treat this as a skip, not a failure."""


class FootballDataClient:
    def __init__(
        self,
        api_key: str | None,
        cache_dir: Path,
        *,
        min_interval: float = MIN_SECONDS_BETWEEN_REQUESTS,
        max_retries: int = MAX_RETRIES,
        session: requests.Session | None = None,
    ) -> None:
        _enable_os_trust_store()
        self.api_key = api_key
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval
        self.max_retries = max_retries
        self._session = session or requests.Session()
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
        validate: Callable[[dict], None] | None = None,
    ) -> dict:
        """Return the JSON for /competitions/{code}/{resource}.

        season (the starting year, e.g. 2024 for 2024/25) picks a season via the
        API's ?season= filter and goes into the cache filename, so a historical
        pull never clobbers the current-season cache. validate, if given, runs on
        every payload (cached or fetched) and must raise to reject it; a
        rejected fetch is not cached.
        """
        cache_path = self._cache_path(competition_code, resource, season)

        if cache_path.exists() and not force_refresh:
            with cache_path.open(encoding="utf-8") as fh:
                payload = json.load(fh)
            if validate:
                validate(payload)
            return payload

        if not self.api_key:
            raise RuntimeError(
                f"No cached response at {cache_path} and no API key set. "
                f"Cannot fetch {competition_code}/{resource}."
            )

        url = f"{BASE_URL}/competitions/{competition_code}/{resource}"
        if season is not None:
            url += f"?season={season}"
        payload = self._request_with_backoff(url)
        if validate:
            validate(payload)
        self._write_atomic(cache_path, payload)
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

    @staticmethod
    def _write_atomic(path: Path, payload: dict) -> None:
        """Write to a temp file in the same folder, then rename over the target."""
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _throttle(self) -> None:
        """Sleep just long enough to keep at least min_interval between calls."""
        elapsed = time.monotonic() - self._last_request_ts
        wait = self.min_interval - elapsed
        if self._last_request_ts and wait > 0:
            time.sleep(wait)

    def _backoff(self, attempt: int) -> float:
        base = BACKOFF_BASE_SECONDS * (2 ** attempt)
        return base + random.uniform(0, base * 0.25)

    def _request_with_backoff(self, url: str) -> dict:
        for attempt in range(self.max_retries):
            self._throttle()
            self._last_request_ts = time.monotonic()
            label = f"(attempt {attempt + 1}/{self.max_retries})"

            try:
                resp = self._session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
            except (requests.ConnectionError, requests.Timeout) as exc:
                wait = self._backoff(attempt)
                log.warning("network error on %s: %s; retrying in %.1fs %s", url, exc, wait, label)
                time.sleep(wait)
                continue

            if resp.status_code == 200:
                return resp.json()

            if resp.status_code == 429:
                wait = self._retry_after_seconds(resp, attempt)
                log.warning("429 rate-limited on %s; backing off %.1fs %s", url, wait, label)
                time.sleep(wait)
                continue

            if 500 <= resp.status_code < 600:
                wait = self._backoff(attempt)
                log.warning("%s server error on %s; retrying in %.1fs %s",
                            resp.status_code, url, wait, label)
                time.sleep(wait)
                continue

            if resp.status_code == 404:
                raise ResourceNotFound(f"404 Not Found: {url}")

            # Any other 4xx (bad key, unknown competition, ...) is not retryable.
            resp.raise_for_status()

        raise RateLimitError(f"Exhausted {self.max_retries} retries against {url}.")

    def _retry_after_seconds(self, resp: requests.Response, attempt: int) -> float:
        """Use the server's Retry-After if present, otherwise exponential backoff."""
        header = resp.headers.get("Retry-After")
        if header:
            try:
                return float(header) + 1.0  # small safety margin
            except ValueError:
                pass
        return self._backoff(attempt)
