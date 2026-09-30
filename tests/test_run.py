from __future__ import annotations

import shutil

import duckdb
import pytest

from ingestion import run
from tests.conftest import FIXTURES


@pytest.fixture
def cache(tmp_path):
    """A private copy of the fixtures, so a test can break one file."""
    target = tmp_path / "raw"
    shutil.copytree(FIXTURES, target)
    return target


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch):
    monkeypatch.setattr(run, "load_dotenv", lambda: None)
    monkeypatch.delenv("FOOTBALL_DATA_API_KEY", raising=False)


def ingest(db, cache, *extra):
    return run.main(["--db", str(db), "--cache-dir", str(cache),
                     "--season", "2024", "--competitions", "PL", *extra])


def runs(db):
    with duckdb.connect(str(db), read_only=True) as con:
        return con.execute(
            "SELECT status, endpoints_loaded, rows_changed FROM raw._load_runs ORDER BY started_at"
        ).fetchall()


def test_fixture_run_loads_and_audits(tmp_path, cache):
    db = tmp_path / "football.duckdb"
    assert ingest(db, cache) == 0
    assert ingest(db, cache) == 0
    first, second = runs(db)
    assert first[:2] == ("success", 3) and first[2] > 0
    assert second == ("success", 3, 0)  # second run changes nothing


def test_one_bad_endpoint_rolls_back_every_endpoint(tmp_path, cache):
    db = tmp_path / "football.duckdb"
    (cache / "PL_standings_2024.json").write_text('{"standings": "not a list"}')

    assert ingest(db, cache) == 1
    with duckdb.connect(str(db), read_only=True) as con:
        counts = [con.execute(f"SELECT count(*) FROM raw.{t}").fetchone()[0]
                  for t in ("teams", "matches", "standings")]
        failures = con.execute("SELECT failures FROM raw._load_runs").fetchone()[0]
    assert counts == [0, 0, 0]
    assert runs(db) == [("failed", 0, 0)]
    assert "PL/standings" in failures


def test_unknown_competition_is_an_error(tmp_path, cache):
    assert run.main(["--db", str(tmp_path / "x.duckdb"), "--competitions", "XX"]) == 2
