from __future__ import annotations

import copy
from datetime import datetime

import pytest

from ingestion.config import MAX_MATCH_DELETES_PER_LOAD
from ingestion.loader import LoadAnomaly, RawLoader

T1 = datetime(2026, 9, 1, 6, 0)
T2 = datetime(2026, 9, 2, 6, 0)


@pytest.fixture
def db(tmp_path):
    return tmp_path / "football.duckdb"


def load_matches(db, response, loaded_at):
    with RawLoader(db, loaded_at=loaded_at) as loader:
        loader.create_schema()
        result = loader.load_matches(response, "PL", "PL_matches_2024.json")
        rows = loader.con.execute(
            "SELECT match_id, _loaded_at FROM raw.matches ORDER BY match_id"
        ).fetchall()
    return result, dict(rows)


def test_first_load_inserts_everything(db, fixture_json):
    result, rows = load_matches(db, fixture_json("PL_matches_2024.json"), T1)
    assert (result.received, result.changed, result.deleted) == (380, 380, 0)
    assert len(rows) == 380


def test_reload_is_idempotent_and_keeps_loaded_at(db, fixture_json):
    response = fixture_json("PL_matches_2024.json")
    load_matches(db, response, T1)
    result, rows = load_matches(db, response, T2)
    assert (result.received, result.changed) == (380, 0)
    assert len(rows) == 380
    assert set(rows.values()) == {T1}  # unchanged rows are not restamped


def test_changed_payload_is_updated_and_restamped(db, fixture_json):
    response = fixture_json("PL_matches_2024.json")
    load_matches(db, response, T1)
    changed = copy.deepcopy(response)
    changed["matches"][0]["score"]["fullTime"]["home"] = 9
    match_id = changed["matches"][0]["id"]

    result, rows = load_matches(db, changed, T2)
    assert result.changed == 1
    assert rows[match_id] == T2
    assert sum(ts == T1 for ts in rows.values()) == 379


def test_match_missing_from_response_is_deleted(db, fixture_json):
    response = fixture_json("PL_matches_2024.json")
    load_matches(db, response, T1)
    trimmed = copy.deepcopy(response)
    removed = trimmed["matches"].pop()["id"]

    result, rows = load_matches(db, trimmed, T2)
    assert result.deleted == 1
    assert removed not in rows and len(rows) == 379


def test_mass_delete_is_refused(db, fixture_json):
    response = fixture_json("PL_matches_2024.json")
    load_matches(db, response, T1)
    trimmed = copy.deepcopy(response)
    del trimmed["matches"][: MAX_MATCH_DELETES_PER_LOAD + 1]

    with pytest.raises(LoadAnomaly, match="would delete"):
        load_matches(db, trimmed, T2)
    with RawLoader(db) as loader:
        assert loader.row_counts()["matches"] == 380  # nothing was deleted


def test_standings_explode_to_one_row_per_team_per_type(db, fixture_json):
    response = fixture_json("PL_standings_2024.json")
    with RawLoader(db, loaded_at=T1) as loader:
        loader.create_schema()
        result = loader.load_standings(response, "PL", "PL_standings_2024.json")
        types = loader.con.execute(
            "SELECT standing_type, count(*) FROM raw.standings GROUP BY 1 ORDER BY 1"
        ).fetchall()
    assert result.received == sum(len(t["table"]) for t in response["standings"])
    assert types == [("AWAY", 20), ("HOME", 20), ("TOTAL", 20)]


def test_standings_rows_without_a_key_are_skipped(db, caplog):
    response = {
        "season": {"id": 1, "currentMatchday": 5},
        "standings": [{"type": "TOTAL", "table": [{"team": {"id": 7}}, {"team": {}}]}],
    }
    with RawLoader(db, loaded_at=T1) as loader:
        loader.create_schema()
        result = loader.load_standings(response, "PL", "x.json")
    assert result.received == 1
    assert "skipped 1 standings row" in caplog.text


def test_rollback_discards_the_whole_run(db, fixture_json):
    with RawLoader(db, loaded_at=T1) as loader:
        loader.create_schema()
        loader.begin()
        loader.load_teams(fixture_json("PL_teams_2024.json"), "PL", "t.json")
        loader.load_matches(fixture_json("PL_matches_2024.json"), "PL", "m.json")
        loader.rollback()
        assert loader.row_counts() == {"teams": 0, "matches": 0, "standings": 0}
