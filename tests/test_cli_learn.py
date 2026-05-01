"""Tests for ``office learn`` (text + JSON output)."""

from __future__ import annotations

import json

import pytest

from office_cli.cli import main


def test_learn_exits_zero_and_meets_rubric(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["learn"]) == 0
    out = capsys.readouterr().out
    assert len(out) >= 200
    for marker in ["purpose", "commands", "exit", "--json", "explain"]:
        assert marker.lower() in out.lower()


def test_learn_json_parseable(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["learn", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tool"] == "office"
    assert payload["json_support"] is True
    assert any(cmd["path"] == ["whoami"] for cmd in payload["commands"])


def test_explain_self(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["explain", "office"]) == 0
    assert capsys.readouterr().out.startswith("#")


def test_explain_root_no_path(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["explain"]) == 0
    out = capsys.readouterr().out
    assert "# office" in out
