"""TTL-cached Slack ``users.list`` directory for ``/whereis`` name
resolution (#38, follow-up A to #29).

When the bare-token MVP from #29 doesn't find an assignment via
local-part match, the handler can fall through to this directory and
try an exact-match lookup against ``display_name`` / ``real_name`` /
``name`` from Slack's user roster.

Two operational concerns drive the design:

* ``users.list`` is paginated and can be slow on large workspaces, so
  results are cached for ``cache_ttl_seconds`` (default 5 min) and
  attempts are rate-limited against transient outages — same pattern
  as :class:`office_cli.people.bamboohr.BambooHRDirectory`.
* Some workspaces have tens of thousands of members and don't want
  this path at all. ``enabled=False`` short-circuits every lookup
  without ever calling the API.

The :class:`SlackDirectoryClient` Protocol intentionally accepts only
the one method the directory uses, so tests pass a fake without
pulling in :mod:`slack_sdk`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Iterable, Protocol

from office_cli.cli._output import emit_diagnostic

_DEFAULT_TTL_SECONDS = 300


@dataclass(frozen=True)
class SlackUser:
    """Subset of a Slack user record we use for name resolution."""

    user_id: str
    display_name: str
    real_name: str
    name: str
    email: str

    def matches(self, token: str) -> bool:
        """Case-insensitive exact match against any of the three name
        fields. Empty fields are skipped — Slack often leaves
        ``display_name`` blank for users who never customized it."""
        needle = token.lower()
        for field in (self.display_name, self.real_name, self.name):
            if field and field.lower() == needle:
                return True
        return False


class SlackDirectoryClient(Protocol):
    """Structural type for the one Slack call this module needs.

    The production implementation is :class:`slack_sdk.web.WebClient`,
    whose ``users_list(cursor=...)`` returns a dict-like response with
    ``members`` and ``response_metadata.next_cursor``.
    """

    def users_list(self, *, cursor: str | None = None) -> Any: ...


class SlackUserDirectory:
    """``users.list``-backed name → email resolver with TTL caching.

    Construct with ``enabled=False`` (or via the
    ``OFFICE_SLACK_DIRECTORY`` env var on the slack-serve entry point)
    to short-circuit every lookup; this is the recommended setting for
    workspaces with tens of thousands of members where pulling the
    full roster every five minutes is wasteful.
    """

    def __init__(
        self,
        client: SlackDirectoryClient | None,
        *,
        enabled: bool = True,
        cache_ttl_seconds: int = _DEFAULT_TTL_SECONDS,
        clock: "callable[[], float] | None" = None,  # type: ignore[name-defined]
    ) -> None:
        self._client = client
        self._enabled = enabled and client is not None
        self._ttl = cache_ttl_seconds
        self._clock = clock or time.monotonic
        self._users: list[SlackUser] = []
        self._cache_at: float = 0.0
        self._last_attempt_at: float = 0.0
        self._has_cache = False
        # Distinct from ``_has_cache``: tracks whether *any* refresh
        # attempt has run, so a failed first fetch still gates
        # subsequent calls within the TTL. Without this, ``now=0.0``
        # under a deterministic clock would leave the
        # ``_last_attempt_at`` gate falsy and bypass rate-limiting on
        # the failure path.
        self._attempted_once = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def iter_users(self) -> list[SlackUser]:
        """Read-only snapshot of the cached roster, refreshed first
        if stale. Used by the #39 fuzzy resolver to seed the
        candidate pool from the Slack workspace; returns ``[]`` when
        the directory is disabled (so callers can union without an
        ``if enabled`` branch each time)."""
        if not self._enabled:
            return []
        self._refresh_if_stale()
        return list(self._users)

    def find_by_name(self, token: str) -> list[SlackUser]:
        """Return every Slack user whose display/real/name field
        equals ``token`` case-insensitively.

        Returns an empty list when the directory is disabled or the
        token is empty. Refresh failures preserve the previous cache
        (fail-open, so a transient Slack outage doesn't block the
        whole resolution chain).
        """
        if not self._enabled or not token:
            return []
        self._refresh_if_stale()
        return [u for u in self._users if u.matches(token)]

    def invalidate(self) -> None:
        self._users = []
        self._cache_at = 0.0
        self._last_attempt_at = 0.0
        self._has_cache = False
        self._attempted_once = False

    def _refresh_if_stale(self) -> None:
        now = self._clock()
        # Gate every refresh on ``_attempted_once`` (success or failure)
        # so a Slack outage on the first call doesn't turn into a
        # request storm — ``_has_cache`` would only be True after a
        # successful fetch, leaving the failure path uncovered.
        if self._attempted_once and (now - self._last_attempt_at) < self._ttl:
            return
        self._attempted_once = True
        try:
            users = list(_fetch_all(self._client))
        except Exception as err:  # noqa: BLE001 — fail-open
            self._last_attempt_at = now
            if self._has_cache:
                age = now - self._cache_at
                emit_diagnostic(
                    f"Slack users.list fetch failed ({err.__class__.__name__}: {err}); "
                    f"serving cached directory from {age:.0f}s ago"
                )
                return
            emit_diagnostic(
                f"Slack users.list fetch failed on first attempt "
                f"({err.__class__.__name__}: {err}); name resolution disabled "
                f"until the next refresh window"
            )
            self._users = []
            return
        self._users = users
        self._cache_at = now
        self._last_attempt_at = now
        self._has_cache = True


def _fetch_all(client: Any) -> Iterable[SlackUser]:
    """Walk ``users_list`` pages and yield filtered :class:`SlackUser`s.

    Skips bots, deleted users, and users without an email — none of
    those can be resolved to a seat assignment, so keeping them in the
    cache wastes memory and makes ambiguous matches worse. The
    per-page filter+dedup loop lives in :func:`_yield_unique_users` so
    this function stays under SonarCloud's cognitive-complexity cap.
    """
    cursor: str | None = None
    seen_user_ids: set[str] = set()
    while True:
        resp = client.users_list(cursor=cursor) or {}
        members = resp.get("members") or []
        yield from _yield_unique_users(members, seen_user_ids)
        meta = resp.get("response_metadata") or {}
        cursor = (meta.get("next_cursor") or "").strip()
        if not cursor:
            return


def _yield_unique_users(
    members: Iterable[dict[str, Any]], seen_user_ids: set[str]
) -> Iterable[SlackUser]:
    """Filter out bots/deleted/no-email entries and dedupe by
    ``user_id``. ``seen_user_ids`` is mutated across pages so cursor
    repeats (rare but observed) yield each user exactly once."""
    for raw in members:
        user = _user_from_member(raw)
        if user is None:
            continue
        if user.user_id in seen_user_ids:
            continue
        seen_user_ids.add(user.user_id)
        yield user


def _user_from_member(raw: dict[str, Any]) -> SlackUser | None:
    if not isinstance(raw, dict):
        return None
    if raw.get("is_bot") or raw.get("deleted"):
        return None
    user_id = (raw.get("id") or "").strip()
    if not user_id:
        return None
    profile = raw.get("profile") or {}
    email = (profile.get("email") or "").strip()
    if not email:
        return None
    return SlackUser(
        user_id=user_id,
        display_name=(profile.get("display_name") or "").strip(),
        real_name=(profile.get("real_name") or "").strip(),
        name=(raw.get("name") or "").strip(),
        email=email,
    )


_DISABLED_VALUES = frozenset({"disabled", "off", "0", "false", "no"})


def parse_directory_enabled(raw: str | None) -> bool:
    """Read the ``OFFICE_SLACK_DIRECTORY`` env value.

    ``None`` / empty / unrecognized → enabled (default-on).
    Any of ``disabled``/``off``/``0``/``false``/``no``
    (case-insensitive) → disabled.
    """
    if raw is None:
        return True
    return raw.strip().lower() not in _DISABLED_VALUES
