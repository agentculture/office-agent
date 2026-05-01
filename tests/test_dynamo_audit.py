"""Tests for the DynamoDB-backed AuditLog."""

from __future__ import annotations

from office_cli.seats import AuditEntry
from office_cli.seats.dynamo import DynamoAuditLog
from tests.test_dynamo_store import FakeDynamoClient


def _audit() -> tuple[FakeDynamoClient, DynamoAuditLog]:
    client = FakeDynamoClient()
    return client, DynamoAuditLog(client, table="office-audit-log")


def test_append_and_all_round_trip() -> None:
    _, log = _audit()
    log.append(
        AuditEntry(
            timestamp="2026-05-01T00:00:01Z",
            actor="cli",
            action="assign",
            seat_id="5-T-01",
            employee_email="alice@example.com",
        )
    )
    rows = log.all()
    assert len(rows) == 1
    assert rows[0].seat_id == "5-T-01"
    assert rows[0].action == "assign"


def test_for_seat_returns_chronological() -> None:
    _, log = _audit()
    log.append_many(
        [
            AuditEntry(
                timestamp="2026-05-02T00:00:00Z",
                actor="cli",
                action="unassign",
                seat_id="5-T-01",
            ),
            AuditEntry(
                timestamp="2026-05-01T00:00:00Z",
                actor="cli",
                action="assign",
                seat_id="5-T-01",
            ),
            AuditEntry(
                timestamp="2026-05-01T00:00:00Z",
                actor="cli",
                action="assign",
                seat_id="5-T-02",
            ),
        ]
    )
    rows = log.for_seat("5-T-01")
    assert [r.action for r in rows] == ["assign", "unassign"]
    # Other seat's entries are not returned.
    assert all(r.seat_id == "5-T-01" for r in rows)


def test_same_second_events_do_not_collide() -> None:
    """Qodo Q2 / Copilot C1 — events at the same wall-clock second
    must not overwrite each other.

    SeatService writes timestamps at second precision; a rapid
    assign → unassign within the same second must keep both rows.
    The composite SK ``timestamp#action#employee_email`` ensures
    DynamoDB's PK+SK dedup happens only on truly identical events.
    """
    _, log = _audit()
    log.append_many(
        [
            AuditEntry(
                timestamp="2026-05-01T00:00:01Z",
                seat_id="5-T-01",
                action="assign",
                actor="cli",
                employee_email="alice@example.com",
            ),
            AuditEntry(
                timestamp="2026-05-01T00:00:01Z",
                seat_id="5-T-01",
                action="unassign",
                actor="cli",
                old_employee_email="alice@example.com",
            ),
        ]
    )
    rows = log.for_seat("5-T-01")
    assert [r.action for r in rows] == ["assign", "unassign"]


def test_idempotent_put_dedups() -> None:
    """Re-running the same batch doesn't duplicate rows — PK+SK key dedups."""
    _, log = _audit()
    entries = [
        AuditEntry(
            timestamp="2026-05-01T00:00:01Z",
            actor="cli",
            action="assign",
            seat_id="5-T-01",
        ),
        AuditEntry(
            timestamp="2026-05-01T00:00:02Z",
            actor="cli",
            action="unassign",
            seat_id="5-T-01",
        ),
    ]
    log.append_many(entries)
    log.append_many(entries)  # re-run
    rows = log.for_seat("5-T-01")
    assert len(rows) == 2  # no duplicates


def test_all_returns_all_seats_chronological() -> None:
    _, log = _audit()
    log.append_many(
        [
            AuditEntry(
                timestamp="2026-05-02T00:00:00Z",
                seat_id="5-T-02",
                action="assign",
                actor="cli",
            ),
            AuditEntry(
                timestamp="2026-05-01T00:00:00Z",
                seat_id="5-T-01",
                action="assign",
                actor="cli",
            ),
        ]
    )
    rows = log.all()
    assert [r.seat_id for r in rows] == ["5-T-01", "5-T-02"]
