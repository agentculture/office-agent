"""End-to-end SeatService test against the Sheets backends.

Exercises the same invariants as ``test_seats_service`` (assign / move /
double-assignment / history) but with ``SheetsStore`` + ``SheetsAuditLog``
behind a ``FakeSheetsClient``. Proves the service is genuinely store-
agnostic.
"""

from __future__ import annotations

from itertools import count
from pathlib import Path

import pytest

from office_cli.cli._errors import OfficeError
from office_cli.floors import parse_svg
from office_cli.offices import load_offices
from office_cli.seats import SeatService
from office_cli.seats.sheets import SheetsAuditLog, SheetsStore
from tests.test_sheets_store import FakeSheetsClient


def _service(data_dir: Path) -> SeatService:
    offices = load_offices(data_dir)
    floor_svgs = {}
    for office in offices.values():
        for floor_id, floor in office.floors.items():
            if floor.svg.is_file():
                floor_svgs[floor_id] = parse_svg(floor.svg)
    client = FakeSheetsClient()
    counter = count(1)

    def clock() -> str:
        return f"2026-05-01T00:00:{next(counter):02d}Z"

    return SeatService(
        offices=offices,
        floor_svgs=floor_svgs,
        store=SheetsStore(client, cache_ttl_seconds=0),
        audit=SheetsAuditLog(client),
        actor="cli",
        clock=clock,
    )


def test_full_flow_against_sheets(data_dir: Path) -> None:
    s = _service(data_dir)
    s.assign("5-T-01", "alice@example.com")
    with pytest.raises(OfficeError):
        s.assign("5-T-02", "alice@example.com")  # one-seat-per-email rule
    moved = s.move("alice@example.com", "5-T-02")
    assert moved.seat_id == "5-T-02"
    history_old = s.history("5-T-01")
    history_new = s.history("5-T-02")
    assert [e.action for e in history_old] == ["assign", "unassign"]
    assert [e.action for e in history_new] == ["assign"]
    assert s.whereis("alice@example.com").seat_id == "5-T-02"
