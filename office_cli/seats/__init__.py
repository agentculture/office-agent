"""Seat assignment store + audit log + business-logic service.

Public surface: the :class:`Assignment` / :class:`AuditEntry` models, the
:class:`AssignmentStore` Protocol, the CSV-backed implementation
(:class:`CsvStore` + :class:`AuditLog`), the business-logic service
(:class:`SeatService`), and the :func:`build_service` factory.

The Sheets-backed implementations live under
:mod:`office_cli.seats.sheets` and are imported lazily so installations
without the ``[sheets]`` extra still work.
"""

from __future__ import annotations

from pathlib import Path

from office_cli._config import (
    StorageConfig,
    assignments_csv,
    audit_log_csv,
    resolve_storage,
)
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

    Reads ``data/offices.yaml``, parses each declared floor SVG, and picks
    the assignment store + audit log per the resolved
    :class:`StorageConfig` (CSV by default, Sheets when configured).
    """
    offices = load_offices(data_dir)
    floor_svgs: dict[str, FloorSvg] = {}
    for office in offices.values():
        for floor_id, floor in office.floors.items():
            if floor.svg.is_file():
                floor_svgs[floor_id] = parse_svg(floor.svg)
    store, audit = _build_backends(data_dir, resolve_storage(data_dir))
    return SeatService(
        offices=offices,
        floor_svgs=floor_svgs,
        store=store,
        audit=audit,
        actor=actor,
    )


def _build_backends(data_dir: Path, cfg: StorageConfig):
    if cfg.type == "csv":
        return (
            CsvStore(assignments_csv(data_dir)),
            AuditLog(audit_log_csv(data_dir)),
        )
    # Lazy import — gspread (and therefore the sheets shim) is optional.
    from office_cli.seats.sheets import GspreadClient, SheetsAuditLog, SheetsStore

    client = GspreadClient(
        spreadsheet_id=cfg.spreadsheet_id,
        service_account_path=cfg.service_account,  # type: ignore[arg-type]
    )
    return (
        SheetsStore(client, cache_ttl_seconds=cfg.cache_ttl_seconds),
        SheetsAuditLog(client),
    )
