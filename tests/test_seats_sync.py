"""Pure tests for the last-write-wins reconciler in ``office_cli.seats._sync``."""

from __future__ import annotations

import pytest

from office_cli.seats import Assignment, AuditEntry
from office_cli.seats._sync import reconcile


def _a(seat_id: str, *, ts: str = "2026-05-01", email: str = "alice@x") -> Assignment:
    return Assignment(
        seat_id=seat_id,
        floor="tlv-floor-5",
        employee_email=email,
        last_updated=ts,
    )


def test_row_only_left_copies_to_right() -> None:
    plan = reconcile([_a("5-T-01")], [], primary="left")
    assert [a.seat_id for a in plan.write_right] == ["5-T-01"]
    assert plan.write_left == []
    assert plan.ties == []


def test_row_only_right_copies_to_left() -> None:
    plan = reconcile([], [_a("5-T-01")], primary="left")
    assert [a.seat_id for a in plan.write_left] == ["5-T-01"]
    assert plan.write_right == []


def test_identical_content_is_noop() -> None:
    a = _a("5-T-01")
    plan = reconcile([a], [a], primary="left")
    assert plan.write_left == []
    assert plan.write_right == []
    assert plan.ties == []


def test_left_newer_writes_right() -> None:
    left = _a("5-T-01", ts="2026-05-02", email="alice@x")
    right = _a("5-T-01", ts="2026-05-01", email="bob@x")
    plan = reconcile([left], [right], primary="left")
    assert plan.write_right == [left]
    assert plan.write_left == []


def test_right_newer_writes_left() -> None:
    left = _a("5-T-01", ts="2026-05-01", email="bob@x")
    right = _a("5-T-01", ts="2026-05-02", email="alice@x")
    plan = reconcile([left], [right], primary="left")
    assert plan.write_left == [right]
    assert plan.write_right == []


def test_tie_breaker_left() -> None:
    left = _a("5-T-01", ts="2026-05-01", email="alice@x")
    right = _a("5-T-01", ts="2026-05-01", email="bob@x")
    plan = reconcile([left], [right], primary="left")
    assert plan.write_right == [left]
    assert plan.ties == ["5-T-01"]


def test_tie_breaker_right() -> None:
    left = _a("5-T-01", ts="2026-05-01", email="alice@x")
    right = _a("5-T-01", ts="2026-05-01", email="bob@x")
    plan = reconcile([left], [right], primary="right")
    assert plan.write_left == [right]
    assert plan.ties == ["5-T-01"]


def test_invalid_primary_rejected() -> None:
    with pytest.raises(ValueError):
        reconcile([], [], primary="middle")


def test_audit_diff_unions_both_sides() -> None:
    left = [
        AuditEntry(timestamp="2026-05-01", seat_id="5-T-01", action="assign", actor="cli"),
    ]
    right = [
        AuditEntry(timestamp="2026-05-02", seat_id="5-T-01", action="unassign", actor="cli"),
    ]
    plan = reconcile([], [], primary="left", left_audit=left, right_audit=right)
    # Right needs the row only-on-left.
    assert [e.action for e in plan.audit_right] == ["assign"]
    # Left needs the row only-on-right.
    assert [e.action for e in plan.audit_left] == ["unassign"]


def test_audit_diff_dedups_by_key() -> None:
    same = AuditEntry(
        timestamp="2026-05-01",
        seat_id="5-T-01",
        action="assign",
        actor="cli",
        employee_email="alice@x",
    )
    plan = reconcile([], [], primary="left", left_audit=[same], right_audit=[same])
    assert plan.audit_left == []
    assert plan.audit_right == []


def test_redacted_flag_does_not_drive_writes() -> None:
    """Stage 7 redacted flag is view-time; never written, so identical
    content with different redacted should still be a no-op."""
    left = Assignment(
        seat_id="5-T-01",
        floor="tlv-floor-5",
        employee_email="exec@x",
        last_updated="2026-05-01",
        hidden=True,
        redacted=False,
    )
    right = Assignment(
        seat_id="5-T-01",
        floor="tlv-floor-5",
        employee_email="exec@x",
        last_updated="2026-05-01",
        hidden=True,
        redacted=True,  # different redacted, same persisted content
    )
    plan = reconcile([left], [right], primary="left")
    assert plan.write_left == []
    assert plan.write_right == []


def test_idempotent_repeated_run() -> None:
    """After applying the plan, a re-run yields an empty plan."""
    left_only = _a("5-T-01")
    right_only = _a("5-T-02")
    # Apply a notional first reconcile by handing each side both rows.
    new_left = [left_only, right_only]
    new_right = [right_only, left_only]
    plan2 = reconcile(new_left, new_right, primary="left")
    assert plan2.write_left == []
    assert plan2.write_right == []
