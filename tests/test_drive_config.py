"""Tests for ``OFFICE_DRIVE_*`` env-var resolution in ``_config.py``."""

from __future__ import annotations

from pathlib import Path

import pytest

from office_cli._config import (
    _drive_cache_root,
    _drive_credentials_path,
    _drive_ttl_seconds,
    resolve_data_dir,
)
from office_cli.cli._errors import EXIT_USER_ERROR, OfficeError


def test_credentials_default_to_sheets_sa(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OFFICE_DRIVE_CREDENTIALS", raising=False)
    path = _drive_credentials_path()
    assert path.name == "sheets-service-account.json"


def test_credentials_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    custom = tmp_path / "custom-sa.json"
    monkeypatch.setenv("OFFICE_DRIVE_CREDENTIALS", str(custom))
    assert _drive_credentials_path() == custom


def test_ttl_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OFFICE_DRIVE_TTL_SECONDS", raising=False)
    assert _drive_ttl_seconds() == 300


def test_ttl_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFFICE_DRIVE_TTL_SECONDS", "120")
    assert _drive_ttl_seconds() == 120


def test_ttl_zero_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFFICE_DRIVE_TTL_SECONDS", "0")
    assert _drive_ttl_seconds() == 0


def test_ttl_negative_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFFICE_DRIVE_TTL_SECONDS", "-1")
    with pytest.raises(OfficeError) as exc:
        _drive_ttl_seconds()
    assert exc.value.code == EXIT_USER_ERROR


def test_ttl_non_integer_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFFICE_DRIVE_TTL_SECONDS", "soon")
    with pytest.raises(OfficeError) as exc:
        _drive_ttl_seconds()
    assert exc.value.code == EXIT_USER_ERROR


def test_cache_root_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OFFICE_DRIVE_CACHE_DIR", raising=False)
    root = _drive_cache_root()
    assert root.name == "drive"
    assert root.parent.name == "office-cli"


def test_cache_root_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OFFICE_DRIVE_CACHE_DIR", str(tmp_path))
    assert _drive_cache_root() == tmp_path


def test_explicit_data_dir_beats_drive_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``--data-dir`` wins over ``OFFICE_DRIVE_ROOT`` so dev loops and
    tests stay on local data when an explicit path is given."""
    monkeypatch.setenv("OFFICE_DRIVE_ROOT", "would-fail-if-hit")
    import argparse

    args = argparse.Namespace(data_dir=str(tmp_path))
    assert resolve_data_dir(args) == tmp_path


def test_office_data_dir_beats_drive_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OFFICE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OFFICE_DRIVE_ROOT", "would-fail-if-hit")
    assert resolve_data_dir() == tmp_path
