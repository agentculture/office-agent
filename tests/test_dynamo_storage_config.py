"""Tests for the DynamoDB branch of ``resolve_storage``."""

from __future__ import annotations

from pathlib import Path

import pytest

from office_cli._config import resolve_storage
from office_cli.cli._errors import EXIT_ENV_ERROR, EXIT_USER_ERROR, OfficeError


def _write(data_dir: Path, body: str) -> None:
    (data_dir / "data").mkdir(parents=True, exist_ok=True)
    (data_dir / "data" / "offices.yaml").write_text(body, encoding="utf-8")


def test_resolve_dynamo_from_yaml(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
storage:
  type: dynamo
  dynamo:
    table_assignments: office-assignments
    table_audit: office-audit-log
    region: us-east-1
""",
    )
    cfg = resolve_storage(tmp_path)
    assert cfg.type == "dynamo"
    assert cfg.table_assignments == "office-assignments"
    assert cfg.table_audit == "office-audit-log"
    assert cfg.region == "us-east-1"


def test_resolve_dynamo_env_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(
        tmp_path,
        """
storage:
  type: dynamo
  dynamo:
    table_assignments: office-assignments
    table_audit: office-audit-log
    region: us-east-1
""",
    )
    monkeypatch.setenv("OFFICE_DYNAMO_REGION", "eu-west-1")
    monkeypatch.setenv("OFFICE_DYNAMO_ASSIGNMENTS", "alt-assignments")
    cfg = resolve_storage(tmp_path)
    assert cfg.region == "eu-west-1"
    assert cfg.table_assignments == "alt-assignments"
    # Non-overridden fields keep YAML values.
    assert cfg.table_audit == "office-audit-log"


def test_dynamo_missing_table_assignments_errors(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
storage:
  type: dynamo
  dynamo:
    table_audit: office-audit-log
    region: us-east-1
""",
    )
    with pytest.raises(OfficeError) as exc:
        resolve_storage(tmp_path)
    assert exc.value.code == EXIT_ENV_ERROR
    assert "table_assignments" in exc.value.message


def test_dynamo_missing_region_errors(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
storage:
  type: dynamo
  dynamo:
    table_assignments: office-assignments
    table_audit: office-audit-log
""",
    )
    with pytest.raises(OfficeError) as exc:
        resolve_storage(tmp_path)
    assert exc.value.code == EXIT_ENV_ERROR
    assert "region" in exc.value.message


def test_dynamo_block_must_be_mapping(tmp_path: Path) -> None:
    _write(tmp_path, "storage:\n  type: dynamo\n  dynamo: nope\n")
    with pytest.raises(OfficeError) as exc:
        resolve_storage(tmp_path)
    assert exc.value.code == EXIT_USER_ERROR
    assert "mapping" in exc.value.message


def test_dynamo_via_env_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No YAML — env-only configuration is sufficient."""
    monkeypatch.setenv("OFFICE_STORE", "dynamo")
    monkeypatch.setenv("OFFICE_DYNAMO_ASSIGNMENTS", "office-assignments")
    monkeypatch.setenv("OFFICE_DYNAMO_AUDIT", "office-audit-log")
    monkeypatch.setenv("OFFICE_DYNAMO_REGION", "us-east-1")
    cfg = resolve_storage(tmp_path)
    assert cfg.type == "dynamo"
    assert cfg.region == "us-east-1"
