"""Tests for the directory selector in office_cli._config."""

from __future__ import annotations

from pathlib import Path

import pytest

from office_cli._config import resolve_directory
from office_cli.cli._errors import OfficeError


def _write(data_dir: Path, body: str) -> None:
    (data_dir / "data").mkdir(parents=True, exist_ok=True)
    (data_dir / "data" / "offices.yaml").write_text(body, encoding="utf-8")


def test_default_is_stub(tmp_path: Path) -> None:
    cfg = resolve_directory(tmp_path)
    assert cfg.type == "stub"


def test_yaml_block_stub(tmp_path: Path) -> None:
    _write(tmp_path, "directory:\n  type: stub\n")
    cfg = resolve_directory(tmp_path)
    assert cfg.type == "stub"


def test_yaml_block_bamboohr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(
        tmp_path,
        """
directory:
  type: bamboohr
  bamboohr:
    subdomain: tipalti
    cache_ttl_seconds: 60
""".lstrip(),
    )
    monkeypatch.setenv("BAMBOOHR_API_TOKEN", "token-xyz")
    monkeypatch.delenv("BAMBOOHR_SUBDOMAIN", raising=False)
    cfg = resolve_directory(tmp_path)
    assert cfg.type == "bamboohr"
    assert cfg.subdomain == "tipalti"
    assert cfg.api_token == "token-xyz"
    assert cfg.cache_ttl_seconds == 60


def test_env_overrides_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path, "directory:\n  type: stub\n")
    monkeypatch.setenv("OFFICE_DIRECTORY", "bamboohr")
    monkeypatch.setenv("BAMBOOHR_SUBDOMAIN", "from-env")
    monkeypatch.setenv("BAMBOOHR_API_TOKEN", "tok")
    cfg = resolve_directory(tmp_path)
    assert cfg.type == "bamboohr"
    assert cfg.subdomain == "from-env"


def test_bamboohr_requires_subdomain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFFICE_DIRECTORY", "bamboohr")
    monkeypatch.setenv("BAMBOOHR_API_TOKEN", "tok")
    monkeypatch.delenv("BAMBOOHR_SUBDOMAIN", raising=False)
    with pytest.raises(OfficeError) as exc:
        resolve_directory(tmp_path)
    assert "subdomain" in exc.value.message


def test_bamboohr_requires_api_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFFICE_DIRECTORY", "bamboohr")
    monkeypatch.setenv("BAMBOOHR_SUBDOMAIN", "x")
    monkeypatch.delenv("BAMBOOHR_API_TOKEN", raising=False)
    with pytest.raises(OfficeError) as exc:
        resolve_directory(tmp_path)
    assert "API token" in exc.value.message
    assert "env-only" in exc.value.remediation


def test_unknown_directory_type_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFFICE_DIRECTORY", "active-directory")
    with pytest.raises(OfficeError) as exc:
        resolve_directory(tmp_path)
    assert "unknown directory type" in exc.value.message


def test_non_dict_bamboohr_block_rejected(tmp_path: Path) -> None:
    _write(tmp_path, "directory:\n  type: bamboohr\n  bamboohr: nope\n")
    with pytest.raises(OfficeError) as exc:
        resolve_directory(tmp_path)
    assert "must be a mapping" in exc.value.message
