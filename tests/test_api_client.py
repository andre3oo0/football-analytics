from __future__ import annotations

import json

import pytest
import requests

from ingestion.api_client import FootballDataClient, RateLimitError, ResourceNotFound
from ingestion.validation import InvalidResponse, validate_matches

GOOD = {"matches": [{"id": 1}], "resultSet": {"count": 1}}


class FakeResponse:
    def __init__(self, status: int, body: dict | None = None, headers: dict | None = None):
        self.status_code = status
        self._body = body or {}
        self.headers = headers or {}

    def json(self) -> dict:
        return self._body

    def raise_for_status(self) -> None:
        raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    """Returns (or raises) the queued outcomes in order and records each URL."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.urls: list[str] = []
        self.headers: dict = {}

    def get(self, url, timeout):
        self.urls.append(url)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_client(tmp_path, *outcomes, api_key="key", max_retries=5):
    session = FakeSession(*outcomes)
    client = FootballDataClient(api_key, tmp_path, min_interval=0,
                                max_retries=max_retries, session=session)
    return client, session


def test_200_is_returned_and_cached(tmp_path):
    client, session = make_client(tmp_path, FakeResponse(200, GOOD))
    assert client.get_competition_resource("PL", "matches", season=2024) == GOOD
    assert session.urls == ["https://api.football-data.org/v4/competitions/PL/matches?season=2024"]
    assert json.loads((tmp_path / "PL_matches_2024.json").read_text()) == GOOD
    # no temp files left behind by the atomic write
    assert [p.name for p in tmp_path.iterdir()] == ["PL_matches_2024.json"]


def test_cache_hit_makes_no_request(tmp_path):
    (tmp_path / "PL_matches.json").write_text(json.dumps(GOOD))
    client, session = make_client(tmp_path)
    assert client.get_competition_resource("PL", "matches") == GOOD
    assert session.urls == []


def test_no_key_and_no_cache_fails(tmp_path):
    client, _ = make_client(tmp_path, api_key=None)
    with pytest.raises(RuntimeError, match="no API key"):
        client.get_competition_resource("PL", "matches")


def test_429_honours_retry_after(tmp_path, no_sleep):
    client, _ = make_client(
        tmp_path, FakeResponse(429, headers={"Retry-After": "12"}), FakeResponse(200, GOOD)
    )
    client.get_competition_resource("PL", "matches")
    assert no_sleep == [13.0]  # Retry-After plus a one-second margin


def test_429_without_retry_after_backs_off_exponentially(tmp_path, no_sleep):
    client, _ = make_client(tmp_path, FakeResponse(429), FakeResponse(429), FakeResponse(200, GOOD))
    client.get_competition_resource("PL", "matches")
    first, second = no_sleep
    assert 5.0 <= first <= 6.25 and 10.0 <= second <= 12.5  # base * 2**n plus up to 25% jitter


def test_5xx_then_200_retries(tmp_path):
    client, session = make_client(tmp_path, FakeResponse(503), FakeResponse(200, GOOD))
    assert client.get_competition_resource("PL", "matches") == GOOD
    assert len(session.urls) == 2


@pytest.mark.parametrize("error", [requests.ConnectionError("reset"), requests.Timeout("slow")])
def test_network_errors_are_retried(tmp_path, error):
    client, session = make_client(tmp_path, error, FakeResponse(200, GOOD))
    assert client.get_competition_resource("PL", "matches") == GOOD
    assert len(session.urls) == 2


def test_retries_are_bounded(tmp_path):
    client, session = make_client(tmp_path, *[FakeResponse(500)] * 3, max_retries=3)
    with pytest.raises(RateLimitError):
        client.get_competition_resource("PL", "matches")
    assert len(session.urls) == 3
    assert not (tmp_path / "PL_matches.json").exists()


def test_404_raises_resource_not_found(tmp_path):
    client, session = make_client(tmp_path, FakeResponse(404))
    with pytest.raises(ResourceNotFound):
        client.get_competition_resource("PL", "standings")
    assert len(session.urls) == 1  # not retried


def test_other_4xx_is_not_retried(tmp_path):
    client, session = make_client(tmp_path, FakeResponse(403))
    with pytest.raises(requests.HTTPError):
        client.get_competition_resource("PL", "matches")
    assert len(session.urls) == 1


def test_invalid_200_body_is_rejected_and_not_cached(tmp_path):
    client, _ = make_client(tmp_path, FakeResponse(200, {"message": "oops"}))
    with pytest.raises(InvalidResponse):
        client.get_competition_resource("PL", "matches", validate=validate_matches)
    assert not (tmp_path / "PL_matches.json").exists()


def test_invalid_cached_body_is_rejected(tmp_path):
    (tmp_path / "PL_matches.json").write_text(json.dumps({"matches": []}))
    client, _ = make_client(tmp_path)
    with pytest.raises(InvalidResponse, match="empty"):
        client.get_competition_resource("PL", "matches", validate=validate_matches)
