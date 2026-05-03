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
    monkeypatch.setenv("OFFICE_BAMBOOHR_ENABLED", "1")
    monkeypatch.setenv("BAMBOOHR_API_TOKEN", "token-xyz")
    monkeypatch.delenv("BAMBOOHR_SUBDOMAIN", raising=False)
    cfg = resolve_directory(tmp_path)
    assert cfg.type == "bamboohr"
    assert cfg.subdomain == "tipalti"
    assert cfg.api_token == "token-xyz"
    assert cfg.cache_ttl_seconds == 60


def test_env_overrides_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path, "directory:\n  type: stub\n")
    monkeypatch.setenv("OFFICE_BAMBOOHR_ENABLED", "1")
    monkeypatch.setenv("OFFICE_DIRECTORY", "bamboohr")
    monkeypatch.setenv("BAMBOOHR_SUBDOMAIN", "from-env")
    monkeypatch.setenv("BAMBOOHR_API_TOKEN", "tok")
    cfg = resolve_directory(tmp_path)
    assert cfg.type == "bamboohr"
    assert cfg.subdomain == "from-env"


def test_bamboohr_requires_subdomain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFFICE_BAMBOOHR_ENABLED", "1")
    monkeypatch.setenv("OFFICE_DIRECTORY", "bamboohr")
    monkeypatch.setenv("BAMBOOHR_API_TOKEN", "tok")
    monkeypatch.delenv("BAMBOOHR_SUBDOMAIN", raising=False)
    with pytest.raises(OfficeError) as exc:
        resolve_directory(tmp_path)
    assert "subdomain" in exc.value.message


def test_bamboohr_requires_api_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFFICE_BAMBOOHR_ENABLED", "1")
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


def test_ttl_capped_at_five_minutes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Qodo Q1: cache_ttl_seconds > 300 violates the v1 5-minute cap."""
    _write(
        tmp_path,
        """
directory:
  type: bamboohr
  bamboohr:
    subdomain: tipalti
    cache_ttl_seconds: 600
""".lstrip(),
    )
    monkeypatch.setenv("OFFICE_BAMBOOHR_ENABLED", "1")
    monkeypatch.setenv("BAMBOOHR_API_TOKEN", "tok")
    with pytest.raises(OfficeError) as exc:
        resolve_directory(tmp_path)
    assert "must not exceed 300" in exc.value.message
    assert "5 minutes" in exc.value.remediation


def test_directory_errors_reference_directory_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Copilot #2/#3: error messages on directory config must say
    'directory.bamboohr.*', not 'storage.*'."""
    _write(
        tmp_path,
        """
directory:
  type: bamboohr
  bamboohr:
    subdomain: tipalti
    cache_ttl_seconds: not-a-number
""".lstrip(),
    )
    monkeypatch.setenv("OFFICE_BAMBOOHR_ENABLED", "1")
    monkeypatch.setenv("BAMBOOHR_API_TOKEN", "tok")
    with pytest.raises(OfficeError) as exc:
        resolve_directory(tmp_path)
    assert "directory.bamboohr.cache_ttl_seconds" in exc.value.message


def test_non_dict_bamboohr_block_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFFICE_BAMBOOHR_ENABLED", "1")
    _write(tmp_path, "directory:\n  type: bamboohr\n  bamboohr: nope\n")
    with pytest.raises(OfficeError) as exc:
        resolve_directory(tmp_path)
    assert "must be a mapping" in exc.value.message


def test_bamboohr_gated_off_falls_back_to_stub(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without OFFICE_BAMBOOHR_ENABLED, bamboohr config silently falls
    back to stub and emits a single warning to stderr."""
    _write(
        tmp_path,
        """
directory:
  type: bamboohr
  bamboohr:
    subdomain: tipalti
""".lstrip(),
    )
    monkeypatch.delenv("OFFICE_BAMBOOHR_ENABLED", raising=False)
    monkeypatch.setenv("BAMBOOHR_API_TOKEN", "tok")
    cfg = resolve_directory(tmp_path)
    assert cfg.type == "stub"
    captured = capsys.readouterr()
    assert "BambooHR backend is gated off" in captured.err
    assert "OFFICE_BAMBOOHR_ENABLED=1" in captured.err


def test_bamboohr_gate_unset_no_creds_does_not_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Misconfigured BambooHR (selected but no creds) must not raise
    when the gate is off — the whole branch is skipped."""
    monkeypatch.delenv("OFFICE_BAMBOOHR_ENABLED", raising=False)
    monkeypatch.setenv("OFFICE_DIRECTORY", "bamboohr")
    monkeypatch.delenv("BAMBOOHR_SUBDOMAIN", raising=False)
    monkeypatch.delenv("BAMBOOHR_API_TOKEN", raising=False)
    cfg = resolve_directory(tmp_path)
    assert cfg.type == "stub"


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "Yes", "on"])
def test_bamboohr_gate_truthy_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("OFFICE_BAMBOOHR_ENABLED", value)
    monkeypatch.setenv("OFFICE_DIRECTORY", "bamboohr")
    monkeypatch.setenv("BAMBOOHR_SUBDOMAIN", "x")
    monkeypatch.setenv("BAMBOOHR_API_TOKEN", "tok")
    cfg = resolve_directory(tmp_path)
    assert cfg.type == "bamboohr"


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "maybe"])
def test_bamboohr_gate_falsy_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("OFFICE_BAMBOOHR_ENABLED", value)
    monkeypatch.setenv("OFFICE_DIRECTORY", "bamboohr")
    monkeypatch.setenv("BAMBOOHR_SUBDOMAIN", "x")
    monkeypatch.setenv("BAMBOOHR_API_TOKEN", "tok")
    cfg = resolve_directory(tmp_path)
    assert cfg.type == "stub"
