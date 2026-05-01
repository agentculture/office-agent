"""End-to-end tests for the auto-vacate killer feature.

When BambooHR stops listing an employee, every seat assigned to them
must render as vacant — without anyone touching the assignment store.
The audit log and the underlying CSV row stay unchanged.
"""

from __future__ import annotations

from itertools import count
from pathlib import Path

from office_cli.floors import parse_svg
from office_cli.offices import load_offices
from office_cli.people import Employee
from office_cli.people.bamboohr import BambooHRDirectory
from office_cli.seats import CsvAuditLog, CsvStore, SeatService
from tests.test_bamboohr_directory import FakeBambooHRClient


def _service(data_dir: Path, directory: BambooHRDirectory) -> SeatService:
    offices = load_offices(data_dir)
    floor_svgs = {}
    for office in offices.values():
        for floor_id, floor in office.floors.items():
            if floor.svg.is_file():
                floor_svgs[floor_id] = parse_svg(floor.svg)
    counter = count(1)

    def clock() -> str:
        return f"2026-05-01T00:00:{next(counter):02d}Z"

    return SeatService(
        offices=offices,
        floor_svgs=floor_svgs,
        store=CsvStore(data_dir / "seats" / "assignments.csv"),
        audit=CsvAuditLog(data_dir / "seats" / "audit-log.csv"),
        actor="cli",
        clock=clock,
        directory=directory,
    )


def test_autovacate_on_offboarding(data_dir: Path) -> None:
    client = FakeBambooHRClient([Employee(email="alice@example.com", name="Alice")])
    now = [0.0]
    directory = BambooHRDirectory(client, cache_ttl_seconds=10, clock=lambda: now[0])
    s = _service(data_dir, directory)

    s.assign("5-T-01", "alice@example.com")
    # While Alice is active: list shows her seat as occupied.
    rows = s.list_seats(only_occupied=True)
    assert [a.seat_id for a in rows] == ["5-T-01"]
    assert s.whereis("alice@example.com").seat_id == "5-T-01"

    # Alice is offboarded in BambooHR.
    client.employees = []
    # Within the cache TTL the seat still appears occupied (5-min staleness
    # is the documented behavior).
    rows = s.list_seats(only_occupied=True)
    assert [a.seat_id for a in rows] == ["5-T-01"]

    # After TTL expires, auto-vacate kicks in.
    now[0] = 100.0
    rows = s.list_seats(only_occupied=True)
    assert rows == []
    rows = s.list_seats(only_vacant=True)
    assert "5-T-01" in {a.seat_id for a in rows}
    assert s.whereis("alice@example.com") is None

    # The data on disk is unchanged: history still shows the original
    # assign, and the CSV row still names alice.
    history = s.history("5-T-01")
    assert [e.action for e in history] == ["assign"]
    raw = (data_dir / "seats" / "assignments.csv").read_text(encoding="utf-8")
    assert "alice@example.com" in raw
