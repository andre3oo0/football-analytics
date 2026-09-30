"""Shape checks on API responses, run before a response is cached or loaded.

A 200 with an unexpected body is the failure that otherwise slips through: the
loader would upsert zero rows and report success, and cache-first mode would
serve the bad file on every later run. Each check raises InvalidResponse, and
the client refuses to cache anything that doesn't pass.
"""

from __future__ import annotations


class InvalidResponse(ValueError):
    """The API returned 200 but the body isn't what this endpoint should return."""


def _require_list(response: dict, key: str) -> list:
    value = response.get(key)
    if not isinstance(value, list):
        raise InvalidResponse(f"expected a '{key}' list, got {type(value).__name__}")
    return value


def validate_teams(response: dict) -> None:
    teams = _require_list(response, "teams")
    if not teams:
        raise InvalidResponse("'teams' is empty")
    expected = response.get("count")
    if expected is not None and expected != len(teams):
        raise InvalidResponse(f"count says {expected} teams, body has {len(teams)}")
    if any("id" not in t for t in teams):
        raise InvalidResponse("a team has no 'id'")


def validate_matches(response: dict) -> None:
    matches = _require_list(response, "matches")
    if not matches:
        raise InvalidResponse("'matches' is empty")
    expected = (response.get("resultSet") or {}).get("count")
    if expected is not None and expected != len(matches):
        raise InvalidResponse(f"resultSet.count says {expected} matches, body has {len(matches)}")
    if any("id" not in m for m in matches):
        raise InvalidResponse("a match has no 'id'")


def validate_standings(response: dict) -> None:
    _require_list(response, "standings")
    if not (response.get("season") or {}).get("id"):
        raise InvalidResponse("standings response has no season.id")


VALIDATORS = {
    "teams": validate_teams,
    "matches": validate_matches,
    "standings": validate_standings,
}
