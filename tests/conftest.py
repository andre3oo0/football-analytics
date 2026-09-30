from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "raw"


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Backoff and throttling sleep for real; tests shouldn't."""
    sleeps: list[float] = []
    monkeypatch.setattr("ingestion.api_client.time.sleep", sleeps.append)
    return sleeps


@pytest.fixture
def fixture_json():
    def load(name: str) -> dict:
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return load
