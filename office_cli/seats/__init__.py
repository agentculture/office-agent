"""Seat assignment store + audit log + business-logic service."""

from __future__ import annotations

from pathlib import Path

from office_cli._config import assignments_csv, audit_log_csv
from office_cli.floors import FloorSvg, parse_svg
from office_cli.offices import load_offices
from office_cli.seats._audit import AuditEntry, AuditLog
from office_cli.seats._csv_store import CsvStore
from office_cli.seats._models import Assignment
from office_cli.seats._service import SeatService
from office_cli.seats._store import AssignmentStore

__all__ = [
    "Assignment",
    "AssignmentStore",
    "AuditEntry",
    "AuditLog",
    "CsvStore",
    "SeatService",
    "build_service",
]


def build_service(data_dir: Path, *, actor: str = "cli") -> SeatService:
    """Wire up a :class:`SeatService` from a data directory.

    Reads ``data/offices.yaml``, parses each declared floor SVG, and points
    the service at the canonical CSV files under ``seats/``.
    """
    offices = load_offices(data_dir)
    floor_svgs: dict[str, FloorSvg] = {}
    for office in offices.values():
        for floor_id, floor in office.floors.items():
            if floor.svg.is_file():
                floor_svgs[floor_id] = parse_svg(floor.svg)
    store = CsvStore(assignments_csv(data_dir))
    audit = AuditLog(audit_log_csv(data_dir))
    return SeatService(
        offices=offices,
        floor_svgs=floor_svgs,
        store=store,
        audit=audit,
        actor=actor,
    )
