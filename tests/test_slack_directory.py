"""Tests for the TTL-cached Slack ``users.list`` directory (#38)."""

from __future__ import annotations

from typing import Any

import pytest

from office_cli.slack._directory import (
    SlackUser,
    SlackUserDirectory,
    parse_directory_enabled,
)


def _resp(members: list[dict[str, Any]], next_cursor: str = "") -> dict[str, Any]:
    """Shape one ``users.list`` response. ``next_cursor=""`` ends a fetch."""
    return {"members": members, "response_metadata": {"next_cursor": next_cursor}}


class FakeSlackDirectoryClient:
    """Stand-in for ``slack_sdk.web.WebClient.users_list``.

    ``responses`` is a queue: each ``users_list(cursor=...)`` call pops
    the next entry. Multi-page fetches consume multiple entries (the
    director loops while ``next_cursor`` is non-empty), so tests
    exercising TTL refresh queue one entry per refresh, and
    pagination tests queue one entry per page within a single
    refresh.
    """

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.calls: list[str | None] = []
        self.errors: list[Exception | None] = []

    def users_list(self, *, cursor: str | None = None) -> Any:
        self.calls.append(cursor)
        if self.errors:
            err = self.errors.pop(0)
            if err is not None:
                raise err
        if not self._responses:
            return _resp([])
        return self._responses.pop(0)


def _alice() -> dict[str, Any]:
    return {
        "id": "U_ALICE",
        "name": "alice",
        "is_bot": False,
        "deleted": False,
        "profile": {
            "display_name": "Alice",
            "real_name": "Alice Smith",
            "email": "alice@example.com",
        },
    }


def _bob() -> dict[str, Any]:
    return {
        "id": "U_BOB",
        "name": "bob",
        "is_bot": False,
        "deleted": False,
        "profile": {"display_name": "Bob", "email": "bob@example.com"},
    }


def _bot() -> dict[str, Any]:
    return {
        "id": "U_BOT",
        "name": "officebot",
        "is_bot": True,
        "deleted": False,
        "profile": {
            "display_name": "Office Bot",
            "real_name": "Office Bot",
            "email": "bot@example.com",
        },
    }


def _deleted() -> dict[str, Any]:
    return {
        "id": "U_OLD",
        "name": "carol",
        "is_bot": False,
        "deleted": True,
        "profile": {"display_name": "Carol", "email": "carol@example.com"},
    }


def _no_email() -> dict[str, Any]:
    return {
        "id": "U_NOEMAIL",
        "name": "guest",
        "is_bot": False,
        "deleted": False,
        "profile": {"display_name": "Guest"},
    }


def test_disabled_directory_never_calls_api() -> None:
    client = FakeSlackDirectoryClient([_resp([_alice()])])
    d = SlackUserDirectory(client, enabled=False)
    assert d.enabled is False
    assert d.find_by_name("alice") == []
    assert client.calls == []


def test_directory_with_no_client_is_disabled_even_when_enabled_true() -> None:
    """Defensive: ``enabled=True`` with ``client=None`` shouldn't crash
    on the first lookup. Treat as disabled."""
    d = SlackUserDirectory(None, enabled=True)
    assert d.enabled is False
    assert d.find_by_name("alice") == []


def test_match_against_display_name_real_name_and_username() -> None:
    client = FakeSlackDirectoryClient([_resp([_alice()])])
    d = SlackUserDirectory(client)
    assert [u.email for u in d.find_by_name("Alice")] == ["alice@example.com"]
    assert [u.email for u in d.find_by_name("alice smith")] == ["alice@example.com"]
    assert [u.email for u in d.find_by_name("alice")] == ["alice@example.com"]
    # Substrings don't match — exact-only is the contract.
    assert d.find_by_name("ali") == []


def test_skips_bots_deleted_and_no_email() -> None:
    client = FakeSlackDirectoryClient([_resp([_alice(), _bot(), _deleted(), _no_email()])])
    d = SlackUserDirectory(client)
    assert [u.email for u in d.find_by_name("Office Bot")] == []
    assert [u.email for u in d.find_by_name("Carol")] == []
    assert [u.email for u in d.find_by_name("Guest")] == []
    assert [u.email for u in d.find_by_name("Alice")] == ["alice@example.com"]


def test_pagination_walks_cursor_until_empty() -> None:
    client = FakeSlackDirectoryClient([_resp([_alice()], next_cursor="next"), _resp([_bob()])])
    d = SlackUserDirectory(client)
    assert [u.email for u in d.find_by_name("Bob")] == ["bob@example.com"]
    # Two pages → cursor=None then cursor="next".
    assert client.calls == [None, "next"]


def test_cache_hits_skip_the_api() -> None:
    """A second lookup within the TTL window must not hit the API."""
    now = [0.0]

    def clock() -> float:
        return now[0]

    client = FakeSlackDirectoryClient([_resp([_alice()])])
    d = SlackUserDirectory(client, cache_ttl_seconds=300, clock=clock)
    d.find_by_name("Alice")
    now[0] = 100.0
    d.find_by_name("Alice")
    assert client.calls == [None]


def test_cache_refreshes_after_ttl() -> None:
    now = [0.0]

    def clock() -> float:
        return now[0]

    client = FakeSlackDirectoryClient([_resp([_alice()]), _resp([_alice()])])
    d = SlackUserDirectory(client, cache_ttl_seconds=300, clock=clock)
    d.find_by_name("Alice")
    now[0] = 1000.0  # past TTL
    d.find_by_name("Alice")
    assert client.calls == [None, None]


def test_refresh_failure_serves_cached_results() -> None:
    """Fail-open: a transient ``users.list`` outage doesn't drop the
    previous cache; subsequent lookups still resolve."""
    now = [0.0]

    def clock() -> float:
        return now[0]

    client = FakeSlackDirectoryClient([_resp([_alice()])])
    d = SlackUserDirectory(client, cache_ttl_seconds=300, clock=clock)
    d.find_by_name("Alice")
    client.errors.append(RuntimeError("slack down"))
    now[0] = 1000.0
    matches = d.find_by_name("Alice")
    assert [u.email for u in matches] == ["alice@example.com"]


def test_first_fetch_failure_returns_empty_without_raising() -> None:
    """First-attempt failure: emit diagnostic, return empty (don't
    crash the slash-command listener)."""
    client = FakeSlackDirectoryClient([])
    client.errors.append(RuntimeError("slack down"))
    d = SlackUserDirectory(client)
    assert d.find_by_name("Alice") == []


def test_invalidate_forces_refetch() -> None:
    client = FakeSlackDirectoryClient([_resp([_alice()]), _resp([_alice()])])
    d = SlackUserDirectory(client)
    d.find_by_name("Alice")
    d.invalidate()
    d.find_by_name("Alice")
    assert client.calls == [None, None]


def test_empty_token_short_circuits() -> None:
    client = FakeSlackDirectoryClient([_resp([_alice()])])
    d = SlackUserDirectory(client)
    assert d.find_by_name("") == []
    assert client.calls == []


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, True),
        ("", True),
        ("enabled", True),
        ("on", True),
        ("yes", True),
        ("disabled", False),
        ("DISABLED", False),
        ("off", False),
        ("0", False),
        ("false", False),
        ("no", False),
        ("  off  ", False),
    ],
)
def test_parse_directory_enabled(raw: str | None, expected: bool) -> None:
    assert parse_directory_enabled(raw) is expected


def test_slack_user_matches_skips_empty_fields() -> None:
    """A user with empty ``display_name`` shouldn't match the empty
    string token (which we already short-circuit, but defense in
    depth)."""
    u = SlackUser(
        user_id="U1",
        display_name="",
        real_name="Alice",
        name="alice",
        email="alice@x.com",
    )
    assert u.matches("Alice") is True
    assert u.matches("") is False


def test_repeated_user_id_across_pages_dedupes() -> None:
    """If Slack repeats an entry across cursors (rare but observed),
    we yield each ``user_id`` exactly once."""
    client = FakeSlackDirectoryClient([_resp([_alice()], next_cursor="next"), _resp([_alice()])])
    d = SlackUserDirectory(client)
    matches = d.find_by_name("Alice")
    assert len(matches) == 1
