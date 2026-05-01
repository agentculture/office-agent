"""Tests for the Stage 7 role-aware redaction in :class:`SeatService`."""

from __future__ import annotations

from itertools import count
from pathlib import Path

from office_cli.seats import build_service


def _service(data_dir: Path):
    counter = count(1)

    def clock() -> str:
        return f"2026-05-01T00:00:{next(counter):02d}Z"

    s = build_service(data_dir)
    s._clock = clock  # noqa: SLF001 — deterministic for tests
    return s


def test_default_role_unrestricted(data_dir: Path) -> None:
    """``role=None`` (CLI default) shows full data on hidden rows."""
    s = _service(data_dir)
    s.assign("5-T-01", "exec@example.com", hidden=True, note="exec note")
    rows = {r.seat_id: r for r in s.list_seats()}
    row = rows["5-T-01"]
    assert row.employee_email == "exec@example.com"
    assert row.notes == "exec note"
    assert row.redacted is False


def test_viewer_redacts_hidden(data_dir: Path) -> None:
    s = _service(data_dir)
    s.assign("5-T-01", "exec@example.com", hidden=True, note="exec note")
    rows = {r.seat_id: r for r in s.list_seats(role="viewer")}
    row = rows["5-T-01"]
    assert row.employee_email == ""
    assert row.notes == ""
    assert row.hidden is True
    assert row.redacted is True


def test_editor_sees_full_hidden(data_dir: Path) -> None:
    s = _service(data_dir)
    s.assign("5-T-01", "exec@example.com", hidden=True, note="exec note")
    rows = {r.seat_id: r for r in s.list_seats(role="editor")}
    row = rows["5-T-01"]
    assert row.employee_email == "exec@example.com"
    assert row.notes == "exec note"
    assert row.redacted is False


def test_planning_matches_editor_in_v1(data_dir: Path) -> None:
    """Planning role gets editor-equivalent visibility for v1."""
    s = _service(data_dir)
    s.assign("5-T-01", "exec@example.com", hidden=True)
    rows = {r.seat_id: r for r in s.list_seats(role="planning")}
    assert rows["5-T-01"].employee_email == "exec@example.com"
    assert rows["5-T-01"].redacted is False


def test_viewer_non_hidden_unchanged(data_dir: Path) -> None:
    """Viewer sees non-hidden rows in full."""
    s = _service(data_dir)
    s.assign("5-T-01", "alice@example.com")
    rows = {r.seat_id: r for r in s.list_seats(role="viewer")}
    assert rows["5-T-01"].employee_email == "alice@example.com"
    assert rows["5-T-01"].redacted is False


def test_viewer_hidden_vacant_does_not_render_private(data_dir: Path) -> None:
    """Hidden + vacant has nothing to hide → ``redacted`` stays False."""
    s = _service(data_dir)
    from office_cli.seats import Assignment

    s.store.upsert(
        Assignment(
            seat_id="5-T-01",
            floor="tlv-floor-5",
            employee_email="",
            hidden=True,
            notes="reserved",
        )
    )
    rows = {r.seat_id: r for r in s.list_seats(role="viewer")}
    row = rows["5-T-01"]
    assert row.employee_email == ""
    assert row.redacted is False
    # The privacy intent on the row stands — notes are still scrubbed.
    assert row.notes == ""


def test_whereis_viewer_redacts(data_dir: Path) -> None:
    s = _service(data_dir)
    s.assign("5-T-01", "exec@example.com", hidden=True)
    a = s.whereis("exec@example.com", role="viewer")
    assert a is not None
    assert a.employee_email == ""
    assert a.redacted is True


def test_whereis_editor_returns_full(data_dir: Path) -> None:
    s = _service(data_dir)
    s.assign("5-T-01", "exec@example.com", hidden=True)
    a = s.whereis("exec@example.com", role="editor")
    assert a is not None
    assert a.employee_email == "exec@example.com"
    assert a.redacted is False


def test_role_with_as_of_filter(data_dir: Path) -> None:
    """Stage 6 + Stage 7: date filter runs first, then role redaction.

    A future-dated hidden row, queried before its window opens, looks
    vacant regardless of role — because the date filter blanks the
    occupant before the role check ever sees it.
    """
    s = _service(data_dir)
    s.assign("5-T-01", "exec@example.com", hidden=True, effective_from="2099-01-01")
    rows = {r.seat_id: r for r in s.list_seats(role="viewer", as_of="2026-05-01")}
    row = rows["5-T-01"]
    assert row.employee_email == ""
    assert row.redacted is False  # not redacted, just not yet effective
