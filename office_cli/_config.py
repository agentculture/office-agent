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
    store_type = (
        (os.environ.get("OFFICE_STORE") or _str_field(yaml_cfg, "type") or "csv").strip().lower()
    )

    if store_type == "csv":
        return StorageConfig(type="csv")

    if store_type != "sheets":
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"unknown storage type: {store_type!r}",
            remediation="set storage.type to 'csv' or 'sheets' in offices.yaml or OFFICE_STORE",
        )

    sheets_cfg = yaml_cfg.get("sheets")
    if sheets_cfg is None:
        sheets_cfg = {}
    if not isinstance(sheets_cfg, dict):
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message="storage.sheets must be a mapping in offices.yaml",
            remediation="see docs/architecture.md for the expected shape",
        )
    spreadsheet_id = (
        os.environ.get("OFFICE_SHEETS_ID") or _str_field(sheets_cfg, "spreadsheet_id") or ""
    ).strip()
    sa_field = os.environ.get("OFFICE_SHEETS_SA") or _str_field(sheets_cfg, "service_account")
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
    ttl = _int_field(sheets_cfg, "cache_ttl_seconds", 300)
    return StorageConfig(
        type="sheets",
        spreadsheet_id=spreadsheet_id,
        service_account=sa_path,
        cache_ttl_seconds=ttl,
    )


def _str_field(d: dict, key: str) -> str:
    """Read ``d[key]`` as a string. ``None`` → empty; non-string → coerced.

    Returns "" for missing keys. Raises :class:`OfficeError` only if the
    value is structurally wrong (a list/dict where a scalar is expected).
    """
    value = d.get(key)
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"storage.{key} must be a scalar, got {type(value).__name__}",
            remediation="see docs/architecture.md for the expected shape",
        )
    return str(value)


def _int_field(d: dict, key: str, default: int) -> int:
    value = d.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"storage.{key} must be an integer, got {type(value).__name__}",
            remediation=f"set storage.{key} to a non-negative integer (seconds)",
        )
    try:
        ttl = int(value)
    except ValueError as err:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"storage.{key} must be an integer; got {value!r}",
            remediation=f"set storage.{key} to a non-negative integer (seconds)",
        ) from err
    if ttl < 0:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"storage.{key} must be non-negative; got {ttl}",
            remediation=f"set storage.{key} to a non-negative integer (seconds)",
        )
    return ttl


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
