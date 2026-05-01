"""TTL-cached BambooHR-backed :class:`EmployeeDirectory`.

Issue #7's "fail-open" guidance: BambooHR being temporarily unreachable
must not stop people from finding their seats. We refresh on a 5-minute
TTL by default; if a refresh fails, we keep serving the previous cache
and emit a stderr diagnostic. The very first fetch has no fallback, so
it surfaces as an :class:`OfficeError` with a clear remediation.
"""

from __future__ import annotations

import time

from office_cli.cli._errors import EXIT_ENV_ERROR, OfficeError
from office_cli.cli._output import emit_diagnostic
from office_cli.people._stub import Employee
from office_cli.people.bamboohr._client import BambooHRClient

_DEFAULT_TTL_SECONDS = 300


class BambooHRDirectory:
    """``EmployeeDirectory`` backed by a BambooHR API client.

    A single in-memory ``{email: Employee}`` cache is refreshed every
    ``cache_ttl_seconds``. ``is_active(email)`` is dict membership;
    ``get(email)`` returns the cached :class:`Employee` or ``None``.
    """

    def __init__(
        self,
        client: BambooHRClient,
        *,
        cache_ttl_seconds: int = _DEFAULT_TTL_SECONDS,
        clock: "callable[[], float] | None" = None,  # type: ignore[name-defined]
    ) -> None:
        self._client = client
        self._ttl = cache_ttl_seconds
        self._clock = clock or time.monotonic
        self._cache: dict[str, Employee] = {}
        self._cache_at: float = 0.0
        # Distinct from `_cache_at`: tracks the *last attempt* (success or
        # fail) so a sustained outage does not retry on every per-seat
        # `is_active` call inside `SeatService.list_seats`.
        self._last_attempt_at: float = 0.0
        self._has_cache = False

    # -- EmployeeDirectory ----------------------------------------------

    def get(self, email: str) -> Employee | None:
        if not email:
            return None
        self._refresh_if_stale()
        return self._cache.get(email)

    def is_active(self, email: str) -> bool:
        return self.get(email) is not None

    # -- Helpers ---------------------------------------------------------

    def _refresh_if_stale(self) -> None:
        now = self._clock()
        # Rate-limit *attempts* (not just successes) so a stale cache during
        # an outage does not trigger one fetch per seat in `list_seats`.
        if self._has_cache and (now - self._last_attempt_at) < self._ttl:
            return
        try:
            employees = self._client.fetch_directory()
        except Exception as err:  # noqa: BLE001 — fail-open by design
            self._last_attempt_at = now
            if self._has_cache:
                age = now - self._cache_at
                emit_diagnostic(
                    f"BambooHR fetch failed ({err.__class__.__name__}: {err}); "
                    f"serving cached directory from {age:.0f}s ago"
                )
                return
            raise OfficeError(
                code=EXIT_ENV_ERROR,
                message=f"BambooHR fetch failed: {err}",
                remediation=("verify BAMBOOHR_API_TOKEN / BAMBOOHR_SUBDOMAIN and retry"),
            ) from err
        self._cache = {e.email: e for e in employees if e.email}
        self._cache_at = now
        self._last_attempt_at = now
        self._has_cache = True

    def invalidate(self) -> None:
        self._cache = {}
        self._cache_at = 0.0
        self._last_attempt_at = 0.0
        self._has_cache = False
