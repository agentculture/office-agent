"""Resolve where the office data (offices.yaml, floors/, seats/) lives,
plus the storage backend (CSV vs Sheets) and people directory (Stub vs
BambooHR) the seat service should use.

Data-dir resolution order:

1. ``--data-dir`` CLI flag (passed through ``args.data_dir``);
2. ``OFFICE_DATA_DIR`` environment variable;
3. the current working directory.

Storage selection order (last wins):

1. ``storage:`` block in ``data/offices.yaml`` (``type: csv`` | ``sheets``);
2. ``OFFICE_STORE`` env var (``csv`` | ``sheets``);
3. CLI overrides via ``OFFICE_SHEETS_ID`` / ``OFFICE_SHEETS_SA``.

Directory selection order (last wins):

1. ``directory:`` block in ``data/offices.yaml`` (``type: stub`` | ``bamboohr``);
2. ``OFFICE_DIRECTORY`` env var (``stub`` | ``bamboohr``);
3. ``BAMBOOHR_API_TOKEN`` / ``BAMBOOHR_SUBDOMAIN`` env overrides.

The API token is intentionally **env-only**; the YAML block carries the
subdomain and TTL but never the token (so YAML can be checked in).
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

from office_cli.cli._errors import EXIT_ENV_ERROR, EXIT_USER_ERROR, OfficeError

_SHAPE_HINT = "see docs/architecture.md for the expected shape"
_BAMBOOHR_TTL_MAX_SECONDS = 300
_PREFIX_SHEETS = "storage.sheets"
_PREFIX_DYNAMO = "storage.dynamo"
_PREFIX_BAMBOOHR = "directory.bamboohr"
_BAMBOOHR_GATE_ENV = "OFFICE_BAMBOOHR_ENABLED"
_TRUTHY = {"1", "true", "yes", "on"}


def _bamboohr_gate_enabled() -> bool:
    return os.environ.get(_BAMBOOHR_GATE_ENV, "").strip().lower() in _TRUTHY


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

    type: str  # "csv" | "sheets" | "dynamo"
    spreadsheet_id: str = ""
    service_account: Path | None = None
    cache_ttl_seconds: int = 300
    # Dynamo-specific. Empty for csv / sheets backends.
    table_assignments: str = ""
    table_audit: str = ""
    region: str = ""


def resolve_storage(data_dir: Path, *, type_override: str | None = None) -> StorageConfig:
    """Pick the storage backend from offices.yaml + env overrides.

    Defaults to ``csv``. Sheets requires both a spreadsheet id and a
    service-account JSON path; we error early if either is missing so
    operators get a clear hint instead of an opaque gspread error.

    ``type_override`` lets callers force a specific backend type
    (csv / sheets / dynamo) without mutating the environment. The
    migrate / sync verbs use this to construct source + target pairs.
    """
    yaml_cfg = _read_storage_block(data_dir)
    if type_override is not None:
        store_type = type_override.strip().lower()
    else:
        store_type = (
            (
                os.environ.get("OFFICE_STORE")
                or _str_field(yaml_cfg, "type", prefix="storage")
                or "csv"
            )
            .strip()
            .lower()
        )

    if store_type == "csv":
        return StorageConfig(type="csv")

    if store_type == "dynamo":
        return _resolve_dynamo(yaml_cfg)

    if store_type != "sheets":
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"unknown storage type: {store_type!r}",
            remediation=(
                "set storage.type to 'csv', 'sheets', or 'dynamo' "
                "in offices.yaml or OFFICE_STORE"
            ),
        )

    sheets_cfg = yaml_cfg.get("sheets")
    if sheets_cfg is None:
        sheets_cfg = {}
    if not isinstance(sheets_cfg, dict):
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message="storage.sheets must be a mapping in offices.yaml",
            remediation=_SHAPE_HINT,
        )
    spreadsheet_id = (
        os.environ.get("OFFICE_SHEETS_ID")
        or _str_field(sheets_cfg, "spreadsheet_id", prefix=_PREFIX_SHEETS)
        or ""
    ).strip()
    sa_field = os.environ.get("OFFICE_SHEETS_SA") or _str_field(
        sheets_cfg, "service_account", prefix=_PREFIX_SHEETS
    )
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
    ttl = _int_field(sheets_cfg, "cache_ttl_seconds", 300, prefix=_PREFIX_SHEETS)
    return StorageConfig(
        type="sheets",
        spreadsheet_id=spreadsheet_id,
        service_account=sa_path,
        cache_ttl_seconds=ttl,
    )


def _resolve_dynamo(yaml_cfg: dict) -> StorageConfig:
    """Build a ``type: dynamo`` :class:`StorageConfig` from YAML + env."""
    dynamo_cfg = yaml_cfg.get("dynamo")
    if dynamo_cfg is None:
        dynamo_cfg = {}
    if not isinstance(dynamo_cfg, dict):
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message="storage.dynamo must be a mapping in offices.yaml",
            remediation=_SHAPE_HINT,
        )
    table_assignments = (
        os.environ.get("OFFICE_DYNAMO_ASSIGNMENTS")
        or _str_field(dynamo_cfg, "table_assignments", prefix=_PREFIX_DYNAMO)
        or ""
    ).strip()
    table_audit = (
        os.environ.get("OFFICE_DYNAMO_AUDIT")
        or _str_field(dynamo_cfg, "table_audit", prefix=_PREFIX_DYNAMO)
        or ""
    ).strip()
    region = (
        os.environ.get("OFFICE_DYNAMO_REGION")
        or _str_field(dynamo_cfg, "region", prefix=_PREFIX_DYNAMO)
        or ""
    ).strip()
    if not table_assignments:
        raise OfficeError(
            code=EXIT_ENV_ERROR,
            message="storage.type=dynamo requires a table_assignments name",
            remediation="set OFFICE_DYNAMO_ASSIGNMENTS or storage.dynamo.table_assignments",
        )
    if not table_audit:
        raise OfficeError(
            code=EXIT_ENV_ERROR,
            message="storage.type=dynamo requires a table_audit name",
            remediation="set OFFICE_DYNAMO_AUDIT or storage.dynamo.table_audit",
        )
    if not region:
        raise OfficeError(
            code=EXIT_ENV_ERROR,
            message="storage.type=dynamo requires an AWS region",
            remediation="set OFFICE_DYNAMO_REGION or storage.dynamo.region",
        )
    ttl = _int_field(dynamo_cfg, "cache_ttl_seconds", 300, prefix=_PREFIX_DYNAMO)
    return StorageConfig(
        type="dynamo",
        table_assignments=table_assignments,
        table_audit=table_audit,
        region=region,
        cache_ttl_seconds=ttl,
    )


def _str_field(d: dict, key: str, *, prefix: str = "storage") -> str:
    """Read ``d[key]`` as a string. ``None`` → empty; non-string → coerced.

    Returns "" for missing keys. Raises :class:`OfficeError` only if the
    value is structurally wrong (a list/dict where a scalar is expected).
    ``prefix`` is the YAML path used in error messages (e.g.
    ``"storage.sheets"`` or ``"directory.bamboohr"``).
    """
    value = d.get(key)
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"{prefix}.{key} must be a scalar, got {type(value).__name__}",
            remediation=_SHAPE_HINT,
        )
    return str(value)


def _int_field(d: dict, key: str, default: int, *, prefix: str = "storage") -> int:
    """Like :func:`_str_field` but coerces to ``int`` and rejects negatives."""
    value = d.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"{prefix}.{key} must be an integer, got {type(value).__name__}",
            remediation=f"set {prefix}.{key} to a non-negative integer (seconds)",
        )
    try:
        ttl = int(value)
    except ValueError as err:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"{prefix}.{key} must be an integer; got {value!r}",
            remediation=f"set {prefix}.{key} to a non-negative integer (seconds)",
        ) from err
    if ttl < 0:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"{prefix}.{key} must be non-negative; got {ttl}",
            remediation=f"set {prefix}.{key} to a non-negative integer (seconds)",
        )
    return ttl


def _read_storage_block(data_dir: Path) -> dict:
    """Return the ``storage:`` mapping from offices.yaml, or empty dict."""
    return _read_top_level_block(data_dir, "storage")


def _read_top_level_block(data_dir: Path, key: str) -> dict:
    """Return the named top-level mapping from offices.yaml, or empty dict.

    Used for the ``storage:`` and ``directory:`` blocks. Malformed YAML
    is swallowed here; ``office_cli.offices.load_offices`` is the
    authoritative parser and raises on it.
    """
    yaml_path = data_dir / "data" / "offices.yaml"
    if not yaml_path.is_file():
        return {}
    with yaml_path.open("r", encoding="utf-8") as f:
        try:
            raw = yaml.safe_load(f) or {}
        except yaml.YAMLError:
            return {}
    block = raw.get(key) or {}
    if not isinstance(block, dict):
        return {}
    return block


@dataclass(frozen=True)
class DirectoryConfig:
    """Resolved people-directory backend for the seat service."""

    type: str  # "stub" | "bamboohr"
    subdomain: str = ""
    api_token: str = ""
    cache_ttl_seconds: int = 300


def resolve_directory(data_dir: Path) -> DirectoryConfig:
    """Pick the directory backend from offices.yaml + env overrides.

    Defaults to ``stub`` (the trust-the-email no-op directory). BambooHR
    requires both a subdomain and an API token; we error early so
    operators get a clear hint instead of an opaque HTTP error.

    The API token is intentionally env-only: ``BAMBOOHR_API_TOKEN`` is
    a secret and must not be committed in ``data/offices.yaml``.
    """
    yaml_cfg = _read_top_level_block(data_dir, "directory")
    dir_type = (
        (
            os.environ.get("OFFICE_DIRECTORY")
            or _str_field(yaml_cfg, "type", prefix="directory")
            or "stub"
        )
        .strip()
        .lower()
    )

    if dir_type == "stub":
        return DirectoryConfig(type="stub")

    if dir_type != "bamboohr":
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"unknown directory type: {dir_type!r}",
            remediation=(
                "set directory.type to 'stub' or 'bamboohr' in offices.yaml or OFFICE_DIRECTORY"
            ),
        )

    if not _bamboohr_gate_enabled():
        print(
            "warning: BambooHR backend is gated off "
            f"(set {_BAMBOOHR_GATE_ENV}=1 to enable); "
            "falling back to stub directory",
            file=sys.stderr,
        )
        return DirectoryConfig(type="stub")

    bamboo_cfg = yaml_cfg.get("bamboohr")
    if bamboo_cfg is None:
        bamboo_cfg = {}
    if not isinstance(bamboo_cfg, dict):
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message="directory.bamboohr must be a mapping in offices.yaml",
            remediation=_SHAPE_HINT,
        )
    subdomain = (
        os.environ.get("BAMBOOHR_SUBDOMAIN")
        or _str_field(bamboo_cfg, "subdomain", prefix=_PREFIX_BAMBOOHR)
        or ""
    ).strip()
    api_token = (os.environ.get("BAMBOOHR_API_TOKEN") or "").strip()
    if not subdomain:
        raise OfficeError(
            code=EXIT_ENV_ERROR,
            message="directory.type=bamboohr requires a subdomain",
            remediation="set BAMBOOHR_SUBDOMAIN or directory.bamboohr.subdomain",
        )
    if not api_token:
        raise OfficeError(
            code=EXIT_ENV_ERROR,
            message="directory.type=bamboohr requires an API token",
            remediation=("set BAMBOOHR_API_TOKEN (env-only — do not commit the token to YAML)"),
        )
    ttl = _int_field(bamboo_cfg, "cache_ttl_seconds", 300, prefix=_PREFIX_BAMBOOHR)
    if ttl > _BAMBOOHR_TTL_MAX_SECONDS:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=(
                f"directory.bamboohr.cache_ttl_seconds must not exceed "
                f"{_BAMBOOHR_TTL_MAX_SECONDS}; got {ttl}"
            ),
            remediation=(
                "the v1 spec caps the BambooHR cache at 5 minutes "
                f"({_BAMBOOHR_TTL_MAX_SECONDS}s) so offboarding propagates promptly"
            ),
        )
    return DirectoryConfig(
        type="bamboohr",
        subdomain=subdomain,
        api_token=api_token,
        cache_ttl_seconds=ttl,
    )
