"""ISO-date helpers for the effective-date window (Stage 6, issue #10).

Effective dates are stored as ``YYYY-MM-DD`` strings (no time component).
``last_updated`` and audit-log timestamps stay full ISO-8601 wall-clock
timestamps; this module only operates on the date-precision values.

Pre-Stage-6 ``Assignment`` rows wrote a full ISO timestamp into
``effective_from``. :func:`is_effective` strips the ``T...`` suffix so
those rows still compare correctly without a migration step.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from office_cli.seats._models import Assignment

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_iso_date(s: str, *, field: str = "date", example: str = "2026-07-01") -> str:
    """Validate ``s`` as ``YYYY-MM-DD`` and return it normalized.

    Raises :class:`office_cli.cli._errors.OfficeError` (``EXIT_USER_ERROR``)
    on malformed input. The error class is imported lazily to avoid a
    circular dependency with the ``office_cli.cli`` package, which itself
    pulls in command modules that import this helper.

    ``example`` is woven into the remediation string so the helper stays
    surface-neutral — CLI callers pass ``"--as-of 2026-07-01"``, the API
    passes ``"?as_of=2026-07-01"``, and Slack falls back to a bare date.
    """
    # Lazy import — see docstring.
    from office_cli.cli._errors import EXIT_USER_ERROR, OfficeError

    if not isinstance(s, str) or not _ISO_DATE_RE.match(s):
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"{field} must be an ISO date (YYYY-MM-DD), got: {s!r}",
            remediation=f"example: {example}",
        )
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError as err:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"{field} is not a real calendar date: {s!r}",
            remediation=f"use a valid YYYY-MM-DD date such as {example.split()[-1]}",
        ) from err
    return s


def today_iso_date(clock: Callable[[], str] | None = None) -> str:
    """Return today's date as ``YYYY-MM-DD``.

    ``clock`` is the same injection point :class:`SeatService` uses; it
    returns a full ISO timestamp like ``2026-05-01T00:00:01Z`` from which
    we take the date prefix. When ``None``, falls back to UTC ``now()``.
    """
    if clock is None:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return _date_prefix(clock())


def is_effective(a: "Assignment", as_of_date: str) -> bool:
    """True iff ``as_of_date`` falls within ``a``'s effective window.

    Empty ``effective_from`` means "always begins"; empty
    ``effective_until`` means "no end". Both bounds are inclusive. Legacy
    rows that store a full ISO timestamp in ``effective_from`` work
    because we strip the ``T...`` suffix before comparison.
    """
    eff_from = _date_prefix(a.effective_from)
    eff_until = _date_prefix(a.effective_until)
    if eff_from and as_of_date < eff_from:
        return False
    if eff_until and as_of_date > eff_until:
        return False
    return True


def validate_window(eff_from: str, eff_until: str) -> None:
    """Reject a window where ``until < from``.

    Both inputs are assumed to already be ``YYYY-MM-DD`` (i.e. they have
    been through :func:`parse_iso_date`). Either may be empty.
    """
    if eff_from and eff_until and eff_until < eff_from:
        from office_cli.cli._errors import EXIT_USER_ERROR, OfficeError

        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=(f"--until ({eff_until}) is before --from ({eff_from})"),
            remediation="swap the values or pick a later --until date",
        )


def _date_prefix(s: str) -> str:
    """Return everything before the first ``T`` (or the whole string)."""
    if not s:
        return ""
    return s.split("T", 1)[0]
