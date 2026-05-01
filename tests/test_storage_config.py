"""Tests for the storage selector in office_cli._config."""

from __future__ import annotations

from pathlib import Path

import pytest

from office_cli._config import resolve_storage
from office_cli.cli._errors import OfficeError


def _write(data_dir: Path, body: str) -> None:
    (data_dir / "data").mkdir(parents=True, exist_ok=True)
    (data_dir / "data" / "offices.yaml").write_text(body, encoding="utf-8")


def test_default_is_csv(tmp_path: Path) -> None:
    cfg = resolve_storage(tmp_path)
    assert cfg.type == "csv"


def test_yaml_block_csv(tmp_path: Path) -> None:
    _write(tmp_path, "storage:\n  type: csv\n")
    cfg = resolve_storage(tmp_path)
    assert cfg.type == "csv"


def test_yaml_block_sheets(tmp_path: Path) -> None:
    sa = tmp_path / "sa.json"
    sa.write_text("{}", encoding="utf-8")
    _write(
        tmp_path,
        f"""
storage:
  type: sheets
  sheets:
    spreadsheet_id: SPREAD123
    service_account: {sa}
    cache_ttl_seconds: 60
""".lstrip(),
    )
    cfg = resolve_storage(tmp_path)
    assert cfg.type == "sheets"
    assert cfg.spreadsheet_id == "SPREAD123"
    assert cfg.service_account == sa
    assert cfg.cache_ttl_seconds == 60


def test_env_overrides_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sa = tmp_path / "sa.json"
    sa.write_text("{}", encoding="utf-8")
    _write(tmp_path, "storage:\n  type: csv\n")
    monkeypatch.setenv("OFFICE_STORE", "sheets")
    monkeypatch.setenv("OFFICE_SHEETS_ID", "FROM_ENV")
    monkeypatch.setenv("OFFICE_SHEETS_SA", str(sa))
    cfg = resolve_storage(tmp_path)
    assert cfg.type == "sheets"
    assert cfg.spreadsheet_id == "FROM_ENV"


def test_sheets_requires_spreadsheet_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFFICE_STORE", "sheets")
    monkeypatch.delenv("OFFICE_SHEETS_ID", raising=False)
    monkeypatch.delenv("OFFICE_SHEETS_SA", raising=False)
    with pytest.raises(OfficeError) as exc:
        resolve_storage(tmp_path)
    assert "spreadsheet id" in exc.value.message


def test_sheets_requires_service_account(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFFICE_STORE", "sheets")
    monkeypatch.setenv("OFFICE_SHEETS_ID", "X")
    monkeypatch.delenv("OFFICE_SHEETS_SA", raising=False)
    with pytest.raises(OfficeError) as exc:
        resolve_storage(tmp_path)
    assert "service-account" in exc.value.message


def test_unknown_store_type_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFFICE_STORE", "dynamo")
    with pytest.raises(OfficeError) as exc:
        resolve_storage(tmp_path)
    assert "unknown storage type" in exc.value.message


def test_relative_service_account_resolves_to_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sa = tmp_path / "creds" / "sa.json"
    sa.parent.mkdir()
    sa.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("OFFICE_STORE", "sheets")
    monkeypatch.setenv("OFFICE_SHEETS_ID", "X")
    monkeypatch.setenv("OFFICE_SHEETS_SA", "creds/sa.json")
    cfg = resolve_storage(tmp_path)
    assert cfg.service_account == sa.resolve()
