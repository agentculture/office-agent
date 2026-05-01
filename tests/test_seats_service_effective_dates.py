"""Tests for the Stage 6 effective-date filter in :class:`SeatService`."""

from __future__ import annotations

from itertools import count
from pathlib import Path

import pytest

from office_cli.cli._errors import EXIT_USER_ERROR, OfficeError
from office_cli.seats import build_service


def _service(data_dir: Path):
    counter = count(1)

    def clock() -> str:
        return f"2026-05-01T00:00:{next(counter):02d}Z"

    s = build_service(data_dir)
    s._clock = clock  # noqa: SLF001 — deterministic for tests
    return s


def test_assign_default_effective_from_is_today_date_only(data_dir: Path) -> None:
    s = _service(data_dir)
    a = s.assign("5-T-01", "alice@example.com")
    assert a.effective_from == "2026-05-01"
    assert a.effective_until == ""
    # ``last_updated`` keeps the full ISO timestamp.
    assert a.last_updated.startswith("2026-05-01T")


def test_assign_with_explicit_window(data_dir: Path) -> None:
    s = _service(data_dir)
    a = s.assign(
        "5-T-01",
        "alice@example.com",
        effective_from="2026-07-01",
        effective_until="2026-12-31",
    )
    assert a.effective_from == "2026-07-01"
    assert a.effective_until == "2026-12-31"


def test_assign_rejects_inverted_window(data_dir: Path) -> None:
    s = _service(data_dir)
    with pytest.raises(OfficeError) as exc:
        s.assign(
            "5-T-01",
            "alice@example.com",
            effective_from="2026-08-01",
            effective_until="2026-07-01",
        )
    assert exc.value.code == EXIT_USER_ERROR


def test_whereis_filters_by_as_of(data_dir: Path) -> None:
    s = _service(data_dir)
    s.assign("5-T-01", "alice@example.com", effective_from="2026-07-01")

    # Default (today, 2026-05-01): the assignment is not yet effective.
    assert s.whereis("alice@example.com", as_of="2026-05-01") is None
    # Future date inside the window: returned.
    a = s.whereis("alice@example.com", as_of="2026-07-15")
    assert a is not None
    assert a.seat_id == "5-T-01"
    # No filter at all: returns the underlying row regardless of date.
    assert s.whereis("alice@example.com") is not None


def test_list_seats_filters_by_as_of(data_dir: Path) -> None:
    s = _service(data_dir)
    s.assign("5-T-01", "alice@example.com", effective_from="2026-07-01")
    s.assign("5-T-02", "bob@example.com")  # default = today

    by_id_pre = {row.seat_id: row for row in s.list_seats(as_of="2026-06-30")}
    # Alice's future-dated row is hidden as vacant.
    assert by_id_pre["5-T-01"].employee_email == ""
    # Bob's row is effective today (2026-05-01) — but as_of=2026-06-30 still
    # falls inside [2026-05-01, ∞).
    assert by_id_pre["5-T-02"].employee_email == "bob@example.com"

    by_id_post = {row.seat_id: row for row in s.list_seats(as_of="2026-07-15")}
    assert by_id_post["5-T-01"].employee_email == "alice@example.com"
    assert by_id_post["5-T-02"].employee_email == "bob@example.com"


def test_list_seats_no_as_of_unchanged(data_dir: Path) -> None:
    s = _service(data_dir)
    s.assign("5-T-01", "alice@example.com", effective_from="2026-07-01")
    by_id = {row.seat_id: row for row in s.list_seats()}
    # Without ``as_of``, the row is returned as-stored — no filtering.
    assert by_id["5-T-01"].employee_email == "alice@example.com"


def test_list_seats_until_excludes_after(data_dir: Path) -> None:
    s = _service(data_dir)
    s.assign(
        "5-T-01",
        "alice@example.com",
        effective_from="2026-07-01",
        effective_until="2026-08-31",
    )
    inside = {r.seat_id: r for r in s.list_seats(as_of="2026-08-01")}
    after = {r.seat_id: r for r in s.list_seats(as_of="2026-09-01")}
    assert inside["5-T-01"].employee_email == "alice@example.com"
    assert after["5-T-01"].employee_email == ""
