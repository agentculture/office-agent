"""End-to-end tests for ``office seats`` commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from office_cli.cli import main


def _data(data_dir: Path) -> list[str]:
    return ["--data-dir", str(data_dir)]


def test_assign_then_list_json(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["seats", "assign", "5-T-01", "alice@example.com", *_data(data_dir)]) == 0
    capsys.readouterr()
    rc = main(["seats", "list", "--json", "--occupied", *_data(data_dir)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["seats"][0]["seat_id"] == "5-T-01"
    assert payload["seats"][0]["employee_email"] == "alice@example.com"


def test_double_assign_emits_error(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["seats", "assign", "5-T-01", "alice@example.com", *_data(data_dir)])
    capsys.readouterr()
    rc = main(["seats", "assign", "5-T-02", "alice@example.com", *_data(data_dir)])
    assert rc == 1
    captured = capsys.readouterr()
    assert "already assigned" in captured.err
    assert "hint:" in captured.err


def test_move_atomic(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["seats", "assign", "5-T-01", "alice@example.com", *_data(data_dir)])
    capsys.readouterr()
    rc = main(["seats", "move", "alice@example.com", "5-T-02", *_data(data_dir)])
    assert rc == 0
    capsys.readouterr()
    rc = main(["seats", "history", "5-T-01", "--json", *_data(data_dir)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    actions = [e["action"] for e in payload["history"]]
    assert actions == ["assign", "unassign"]


def test_unassign(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["seats", "assign", "5-T-01", "alice@example.com", *_data(data_dir)])
    capsys.readouterr()
    rc = main(["seats", "unassign", "5-T-01", *_data(data_dir)])
    assert rc == 0


def test_unknown_seat_user_error(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["seats", "assign", "9-Q-99", "alice@example.com", *_data(data_dir)])
    assert rc == 1
    assert "unknown seat" in capsys.readouterr().err


def test_list_text_smoke(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["seats", "list", *_data(data_dir)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "5-T-01" in out
