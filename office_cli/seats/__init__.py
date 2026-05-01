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
    DirectoryConfig,
    StorageConfig,
    assignments_csv,
    audit_log_csv,
    resolve_directory,
    resolve_storage,
)
from office_cli.floors import FloorSvg, parse_svg
from office_cli.offices import load_offices
from office_cli.people import EmployeeDirectory, StubDirectory
from office_cli.seats._audit import AuditLog, CsvAuditLog
from office_cli.seats._csv_store import CsvStore
from office_cli.seats._models import Assignment, AuditEntry
from office_cli.seats._service import SeatService
from office_cli.seats._store import AssignmentStore

__all__ = [
    "Assignment",
    "AssignmentStore",
    "AuditEntry",
    "AuditLog",
    "CsvAuditLog",
    "CsvStore",
    "DirectoryConfig",
    "SeatService",
    "StorageConfig",
    "build_service",
]


def build_service(data_dir: Path, *, actor: str = "cli") -> SeatService:
    """Wire up a :class:`SeatService` from a data directory.

    Reads ``data/offices.yaml``, parses each declared floor SVG, and picks
    the assignment store + audit log per the resolved
    :class:`StorageConfig` (CSV by default, Sheets when configured), plus
    the people directory per the resolved :class:`DirectoryConfig` (stub
    by default, BambooHR when configured).
    """
    offices = load_offices(data_dir)
    floor_svgs: dict[str, FloorSvg] = {}
    for office in offices.values():
        for floor_id, floor in office.floors.items():
            if floor.svg.is_file():
                floor_svgs[floor_id] = parse_svg(floor.svg)
    store, audit = _build_backends(data_dir, resolve_storage(data_dir))
    directory = _build_directory(resolve_directory(data_dir))
    return SeatService(
        offices=offices,
        floor_svgs=floor_svgs,
        store=store,
        audit=audit,
        actor=actor,
        directory=directory,
    )


def _build_directory(cfg: DirectoryConfig) -> EmployeeDirectory:
    if cfg.type == "stub":
        return StubDirectory()
    # Lazy import — requests is optional.
    from office_cli.people.bamboohr import (
        BambooHRDirectory,
        RequestsBambooHRClient,
    )

    client = RequestsBambooHRClient(
        subdomain=cfg.subdomain,
        api_token=cfg.api_token,
    )
    return BambooHRDirectory(client, cache_ttl_seconds=cfg.cache_ttl_seconds)


def _build_backends(data_dir: Path, cfg: StorageConfig):
    if cfg.type == "csv":
        return (
            CsvStore(assignments_csv(data_dir)),
            CsvAuditLog(audit_log_csv(data_dir)),
        )
    if cfg.type == "dynamo":
        # Lazy import — boto3 (and therefore the dynamo shim) is optional.
        from office_cli.seats.dynamo import (
            Boto3DynamoClient,
            DynamoAuditLog,
            DynamoStore,
        )

        client = Boto3DynamoClient(region=cfg.region)
        return (
            DynamoStore(
                client,
                table=cfg.table_assignments,
                cache_ttl_seconds=cfg.cache_ttl_seconds,
            ),
            DynamoAuditLog(client, table=cfg.table_audit),
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


def build_backends_for_type(data_dir: Path, store_type: str):
    """Resolve a ``StorageConfig`` for ``store_type`` and build (store, audit).

    Used by ``office seats migrate`` and ``office seats sync`` to spin up
    a source / target pair driven by ``--from`` / ``--to`` flags. Reads
    the same env / YAML config as :func:`build_service` would for that
    type, with the type override applied last.
    """
    import os as _os  # local — avoid widening the module-level surface.

    prior = _os.environ.get("OFFICE_STORE")
    _os.environ["OFFICE_STORE"] = store_type
    try:
        cfg = resolve_storage(data_dir)
    finally:
        if prior is None:
            _os.environ.pop("OFFICE_STORE", None)
        else:
            _os.environ["OFFICE_STORE"] = prior
    return _build_backends(data_dir, cfg)
