"""Tests for ``office whoami`` (auth probe stub)."""

from __future__ import annotations

import json

import pytest

from office_cli.cli import main


def test_whoami_text_unauthenticated(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["whoami"]) == 0
    assert capsys.readouterr().out.strip() == "unauthenticated"


def test_whoami_json_payload(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["whoami", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "unauthenticated"
    assert payload["user"] is None
    assert set(payload["backends"]) == {"bamboohr", "google_sheets", "slack"}
    assert all(v == "unconfigured" for v in payload["backends"].values())


def test_whoami_help_smoke(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["whoami", "--help"])
    assert exc.value.code == 0
    assert "Probe authentication state" in capsys.readouterr().out
