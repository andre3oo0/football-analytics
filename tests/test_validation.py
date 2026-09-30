from __future__ import annotations

import pytest

from ingestion.validation import (
    InvalidResponse,
    validate_matches,
    validate_standings,
    validate_teams,
)


def test_real_fixtures_pass(fixture_json):
    validate_teams(fixture_json("BL1_teams_2024.json"))
    validate_matches(fixture_json("BL1_matches_2024.json"))
    validate_standings(fixture_json("BL1_standings_2024.json"))


@pytest.mark.parametrize("body, message", [
    ({}, "expected a 'matches' list"),
    ({"matches": None}, "expected a 'matches' list"),
    ({"matches": []}, "empty"),
    ({"matches": [{"id": 1}], "resultSet": {"count": 380}}, "resultSet.count says 380"),
    ({"matches": [{"status": "FINISHED"}]}, "no 'id'"),
])
def test_bad_matches_bodies(body, message):
    with pytest.raises(InvalidResponse, match=message):
        validate_matches(body)


def test_team_count_mismatch():
    with pytest.raises(InvalidResponse, match="count says 20"):
        validate_teams({"teams": [{"id": 1}], "count": 20})


def test_standings_needs_season_id():
    with pytest.raises(InvalidResponse, match="season.id"):
        validate_standings({"standings": []})
