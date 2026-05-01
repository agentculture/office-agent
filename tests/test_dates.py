"""Tests for ``office_cli._dates``."""

from __future__ import annotations

import pytest

from office_cli._dates import (
    is_effective,
    parse_iso_date,
    today_iso_date,
    validate_window,
)
from office_cli.cli._errors import EXIT_USER_ERROR, OfficeError
from office_cli.seats import Assignment


def test_parse_iso_date_accepts_valid() -> None:
    assert parse_iso_date("2026-07-01", field="--as-of") == "2026-07-01"
    assert parse_iso_date("2026-12-31", field="--from") == "2026-12-31"


@pytest.mark.parametrize(
    "bad",
    [
        "2026-7-1",  # missing zero pad
        "2026/07/01",  # wrong separator
        "07-01-2026",  # wrong order
        "2026-07-01T00:00:00Z",  # full ISO
        "2026-13-01",  # bad month
        "2026-02-30",  # not a real date
        "",
        "today",
    ],
)
def test_parse_iso_date_rejects_malformed(bad: str) -> None:
    with pytest.raises(OfficeError) as exc:
        parse_iso_date(bad, field="--as-of")
    assert exc.value.code == EXIT_USER_ERROR
    assert "--as-of" in exc.value.message


def test_today_iso_date_strips_time_from_clock() -> None:
    assert today_iso_date(lambda: "2026-05-01T12:34:56Z") == "2026-05-01"


def test_today_iso_date_default() -> None:
    # Just check shape — UTC today is fine for this assertion.
    out = today_iso_date()
    assert len(out) == 10
    assert out[4] == "-" and out[7] == "-"


def test_is_effective_window_inclusive() -> None:
    a = Assignment(
        seat_id="5-T-01",
        floor="tlv-floor-5",
        effective_from="2026-07-01",
        effective_until="2026-08-31",
    )
    assert is_effective(a, "2026-07-01") is True
    assert is_effective(a, "2026-08-31") is True
    assert is_effective(a, "2026-06-30") is False
    assert is_effective(a, "2026-09-01") is False


def test_is_effective_open_bounds() -> None:
    a = Assignment(seat_id="5-T-01", floor="tlv-floor-5")  # both empty
    assert is_effective(a, "1999-01-01") is True
    assert is_effective(a, "2099-01-01") is True

    a_from = Assignment(seat_id="5-T-01", floor="tlv-floor-5", effective_from="2026-07-01")
    assert is_effective(a_from, "2026-06-30") is False
    assert is_effective(a_from, "2099-12-31") is True

    a_until = Assignment(seat_id="5-T-01", floor="tlv-floor-5", effective_until="2026-07-01")
    assert is_effective(a_until, "2026-07-02") is False
    assert is_effective(a_until, "1999-01-01") is True


def test_is_effective_strips_legacy_full_iso() -> None:
    """Pre-Stage-6 rows store ``effective_from`` as a full ISO timestamp."""
    a = Assignment(
        seat_id="5-T-01",
        floor="tlv-floor-5",
        effective_from="2026-07-01T00:00:01Z",
    )
    # Without prefix-stripping, the lex comparison "2026-07-01T..." > "2026-07-01"
    # would mark the row as not yet effective on its start day. Strip it.
    assert is_effective(a, "2026-07-01") is True


def test_validate_window_accepts_valid() -> None:
    validate_window("2026-07-01", "2026-08-01")
    validate_window("2026-07-01", "")
    validate_window("", "2026-07-01")
    validate_window("", "")


def test_validate_window_rejects_inverted() -> None:
    with pytest.raises(OfficeError) as exc:
        validate_window("2026-08-01", "2026-07-01")
    assert exc.value.code == EXIT_USER_ERROR
    assert "before" in exc.value.message
