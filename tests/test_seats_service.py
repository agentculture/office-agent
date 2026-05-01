"""Tests for the SeatService business logic."""

from __future__ import annotations

from itertools import count
from pathlib import Path

import pytest

from office_cli.cli._errors import OfficeError
from office_cli.seats import build_service


def _service(data_dir: Path):
    """Build a service whose clock is deterministic."""
    counter = count(1)

    def clock() -> str:
        return f"2026-05-01T00:00:{next(counter):02d}Z"

    service = build_service(data_dir)
    service._clock = clock  # noqa: SLF001 - test injection
    return service


def test_assign_writes_audit(data_dir: Path) -> None:
    s = _service(data_dir)
    a = s.assign("5-T-01", "alice@example.com", note="welcome")
    assert a.employee_email == "alice@example.com"
    assert a.floor == "tlv-floor-5"
    history = s.history("5-T-01")
    assert [e.action for e in history] == ["assign"]
    assert history[0].employee_email == "alice@example.com"


def test_double_assignment_rejected(data_dir: Path) -> None:
    s = _service(data_dir)
    s.assign("5-T-01", "alice@example.com")
    with pytest.raises(OfficeError) as exc:
        s.assign("5-T-02", "alice@example.com")
    assert exc.value.code == 1
    assert "already assigned" in exc.value.message


def test_assign_to_occupied_seat_rejected(data_dir: Path) -> None:
    s = _service(data_dir)
    s.assign("5-T-01", "alice@example.com")
    with pytest.raises(OfficeError):
        s.assign("5-T-01", "bob@example.com")


def test_unknown_seat_rejected(data_dir: Path) -> None:
    s = _service(data_dir)
    with pytest.raises(OfficeError) as exc:
        s.assign("9-Q-99", "alice@example.com")
    assert "unknown seat" in exc.value.message


def test_unassign_then_reassign(data_dir: Path) -> None:
    s = _service(data_dir)
    s.assign("5-T-01", "alice@example.com")
    s.unassign("5-T-01")
    assert s.whereis("alice@example.com") is None
    s.assign("5-T-01", "bob@example.com")
    assert s.whereis("bob@example.com").seat_id == "5-T-01"


def test_unassign_vacant_rejected(data_dir: Path) -> None:
    s = _service(data_dir)
    with pytest.raises(OfficeError) as exc:
        s.unassign("5-T-01")
    assert "vacant" in exc.value.message


def test_move_atomic(data_dir: Path) -> None:
    s = _service(data_dir)
    s.assign("5-T-01", "alice@example.com")
    moved = s.move("alice@example.com", "5-T-02")
    assert moved.seat_id == "5-T-02"
    assert s.whereis("alice@example.com").seat_id == "5-T-02"
    # 5-T-01 is now vacant; history shows both transitions.
    h1 = s.history("5-T-01")
    h2 = s.history("5-T-02")
    assert [e.action for e in h1] == ["assign", "unassign"]
    assert [e.action for e in h2] == ["assign"]


def test_move_to_occupied_rejected(data_dir: Path) -> None:
    s = _service(data_dir)
    s.assign("5-T-01", "alice@example.com")
    s.assign("5-T-02", "bob@example.com")
    with pytest.raises(OfficeError):
        s.move("alice@example.com", "5-T-02")


def test_move_unknown_email_rejected(data_dir: Path) -> None:
    s = _service(data_dir)
    with pytest.raises(OfficeError) as exc:
        s.move("ghost@example.com", "5-T-01")
    assert "no current seat" in exc.value.message


def test_list_filters(data_dir: Path) -> None:
    s = _service(data_dir)
    s.assign("5-T-01", "alice@example.com")
    rows = s.list_seats()
    assert len(rows) == 9  # 8 seats + 1 room from the fixture SVG
    occupied = s.list_seats(only_occupied=True)
    assert [a.seat_id for a in occupied] == ["5-T-01"]
    vacant = s.list_seats(only_vacant=True)
    assert "5-T-01" not in {a.seat_id for a in vacant}
    cluster_t = s.list_seats(cluster="T")
    assert all(a.seat_id.split("-")[1] == "T" for a in cluster_t)


def test_history_sorted_by_timestamp(data_dir: Path) -> None:
    """Qodo #5: history must be chronological even if the audit log is reordered."""
    s = build_service(data_dir)
    # Synthesize out-of-order audit entries directly.
    from office_cli.seats._models import AuditEntry

    s.audit.append_many(
        [
            AuditEntry(
                timestamp="2026-05-01T00:00:02Z",
                actor="t",
                action="assign",
                seat_id="5-T-01",
                employee_email="b@x",
            ),
            AuditEntry(
                timestamp="2026-05-01T00:00:01Z",
                actor="t",
                action="assign",
                seat_id="5-T-01",
                employee_email="a@x",
            ),
        ]
    )
    history = s.history("5-T-01")
    assert [e.timestamp for e in history] == sorted(e.timestamp for e in history)


def test_room_assignable(data_dir: Path) -> None:
    s = _service(data_dir)
    a = s.assign("5.18", "exec@example.com")
    assert a.seat_id == "5.18"
