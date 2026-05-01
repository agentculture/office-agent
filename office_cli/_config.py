"""Resolve where the office data (offices.yaml, floors/, seats/) lives,
plus the storage backend (CSV vs Sheets) the seat service should use.

Data-dir resolution order:

1. ``--data-dir`` CLI flag (passed through ``args.data_dir``);
2. ``OFFICE_DATA_DIR`` environment variable;
3. the current working directory.

Storage selection order (last wins):

1. ``storage:`` block in ``data/offices.yaml`` (``type: csv`` | ``sheets``);
2. ``OFFICE_STORE`` env var (``csv`` | ``sheets``);
3. CLI overrides via ``OFFICE_SHEETS_ID`` / ``OFFICE_SHEETS_SA``.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from office_cli.cli._errors import EXIT_ENV_ERROR, EXIT_USER_ERROR, OfficeError


def resolve_data_dir(args: argparse.Namespace | None = None) -> Path:
    explicit = getattr(args, "data_dir", None) if args is not None else None
    candidate: Path
    if explicit:
        candidate = Path(explicit).expanduser()
    elif os.environ.get("OFFICE_DATA_DIR"):
        candidate = Path(os.environ["OFFICE_DATA_DIR"]).expanduser()
    else:
        candidate = Path.cwd()
    if not candidate.is_dir():
        raise OfficeError(
            code=EXIT_ENV_ERROR,
            message=f"data dir does not exist: {candidate}",
            remediation="pass --data-dir or set OFFICE_DATA_DIR to the office-agent checkout",
        )
    return candidate


def add_data_dir_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--data-dir",
        help="Directory containing data/offices.yaml, floors/, seats/. "
        "Defaults to $OFFICE_DATA_DIR or the current working directory.",
    )


def assignments_csv(data_dir: Path) -> Path:
    return data_dir / "seats" / "assignments.csv"


def audit_log_csv(data_dir: Path) -> Path:
    return data_dir / "seats" / "audit-log.csv"


@dataclass(frozen=True)
class StorageConfig:
    """Resolved storage backend for the seat service."""

    type: str  # "csv" | "sheets"
    spreadsheet_id: str = ""
    service_account: Path | None = None
    cache_ttl_seconds: int = 300


def resolve_storage(data_dir: Path) -> StorageConfig:
    """Pick the storage backend from offices.yaml + env overrides.

    Defaults to ``csv``. Sheets requires both a spreadsheet id and a
    service-account JSON path; we error early if either is missing so
    operators get a clear hint instead of an opaque gspread error.
    """
    yaml_cfg = _read_storage_block(data_dir)
    store_type = (os.environ.get("OFFICE_STORE") or yaml_cfg.get("type") or "csv").strip().lower()

    if store_type == "csv":
        return StorageConfig(type="csv")

    if store_type != "sheets":
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"unknown storage type: {store_type!r}",
            remediation="set storage.type to 'csv' or 'sheets' in offices.yaml or OFFICE_STORE",
        )

    sheets_cfg = yaml_cfg.get("sheets") or {}
    spreadsheet_id = (
        os.environ.get("OFFICE_SHEETS_ID") or sheets_cfg.get("spreadsheet_id") or ""
    ).strip()
    sa_field = os.environ.get("OFFICE_SHEETS_SA") or sheets_cfg.get("service_account")
    if not spreadsheet_id:
        raise OfficeError(
            code=EXIT_ENV_ERROR,
            message="storage.type=sheets requires a spreadsheet id",
            remediation="set OFFICE_SHEETS_ID or storage.sheets.spreadsheet_id",
        )
    if not sa_field:
        raise OfficeError(
            code=EXIT_ENV_ERROR,
            message="storage.type=sheets requires a service-account JSON",
            remediation="set OFFICE_SHEETS_SA or storage.sheets.service_account",
        )
    sa_path = Path(sa_field).expanduser()
    if not sa_path.is_absolute():
        sa_path = (data_dir / sa_path).resolve()
    ttl = int(sheets_cfg.get("cache_ttl_seconds", 300))
    return StorageConfig(
        type="sheets",
        spreadsheet_id=spreadsheet_id,
        service_account=sa_path,
        cache_ttl_seconds=ttl,
    )


def _read_storage_block(data_dir: Path) -> dict:
    """Return the ``storage:`` mapping from offices.yaml, or empty dict."""
    yaml_path = data_dir / "data" / "offices.yaml"
    if not yaml_path.is_file():
        return {}
    with yaml_path.open("r", encoding="utf-8") as f:
        try:
            raw = yaml.safe_load(f) or {}
        except yaml.YAMLError:
            # offices.py raises on malformed YAML; here we just decline to
            # apply storage config and let the rest of the loader complain.
            return {}
    storage = raw.get("storage") or {}
    if not isinstance(storage, dict):
        return {}
    return storage
