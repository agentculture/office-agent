"""Tests for ``office_cli._roles``."""

from __future__ import annotations

from pathlib import Path

import pytest

from office_cli._roles import (
    EDITOR,
    PLANNING,
    VIEWER,
    RolesConfig,
    is_full_access,
    resolve_roles,
    role_for_email,
)
from office_cli.cli._errors import EXIT_USER_ERROR, OfficeError


def _write_yaml(data_dir: Path, body: str) -> None:
    (data_dir / "data").mkdir(parents=True, exist_ok=True)
    (data_dir / "data" / "offices.yaml").write_text(body, encoding="utf-8")


def test_resolve_missing_yaml_returns_empty_config(tmp_path: Path) -> None:
    cfg = resolve_roles(tmp_path)
    assert cfg == RolesConfig()


def test_resolve_no_roles_block(tmp_path: Path) -> None:
    _write_yaml(tmp_path, "offices: []\n")
    cfg = resolve_roles(tmp_path)
    assert cfg == RolesConfig()


def test_resolve_basic_mapping(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path,
        """
roles:
  editor:
    - "alice@tipalti.com"
    - "HR-IT@tipalti.com"
  planning:
    - "Facilities@tipalti.com"
""",
    )
    cfg = resolve_roles(tmp_path)
    # Emails normalize to lowercase at parse time.
    assert "alice@tipalti.com" in cfg.editor
    assert "hr-it@tipalti.com" in cfg.editor
    assert "facilities@tipalti.com" in cfg.planning


def test_role_for_email_case_insensitive(tmp_path: Path) -> None:
    cfg = RolesConfig(editor=frozenset({"alice@tipalti.com"}))
    assert role_for_email(cfg, "alice@tipalti.com") == EDITOR
    assert role_for_email(cfg, "ALICE@TIPALTI.COM") == EDITOR
    assert role_for_email(cfg, " Alice@Tipalti.com ") == EDITOR
    assert role_for_email(cfg, "bob@tipalti.com") == VIEWER
    assert role_for_email(cfg, "") == VIEWER


def test_role_for_email_planning(tmp_path: Path) -> None:
    cfg = RolesConfig(planning=frozenset({"facilities@x.com"}))
    assert role_for_email(cfg, "facilities@x.com") == PLANNING


def test_resolve_rejects_string_value(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path,
        """
roles:
  editor: "alice@tipalti.com"
""",
    )
    with pytest.raises(OfficeError) as exc:
        resolve_roles(tmp_path)
    assert exc.value.code == EXIT_USER_ERROR
    assert "list" in exc.value.message


def test_resolve_rejects_non_string_entry(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path,
        """
roles:
  editor:
    - 123
""",
    )
    with pytest.raises(OfficeError) as exc:
        resolve_roles(tmp_path)
    assert exc.value.code == EXIT_USER_ERROR


def test_resolve_rejects_string_block(tmp_path: Path) -> None:
    _write_yaml(tmp_path, "roles: oops\n")
    with pytest.raises(OfficeError):
        resolve_roles(tmp_path)


def test_is_full_access() -> None:
    assert is_full_access(None) is True  # CLI default
    assert is_full_access(EDITOR) is True
    assert is_full_access(PLANNING) is True
    assert is_full_access(VIEWER) is False
    assert is_full_access("unknown") is False
