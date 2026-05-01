"""End-to-end tests for ``office whereis``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from office_cli.cli import main


def test_whereis_no_seat(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["whereis", "ghost@example.com", "--json", "--data-dir", str(data_dir)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["assignment"] is None


def test_whereis_after_assign(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(
        [
            "seats",
            "assign",
            "5-T-01",
            "alice@example.com",
            "--data-dir",
            str(data_dir),
        ]
    )
    capsys.readouterr()
    rc = main(["whereis", "alice@example.com", "--json", "--data-dir", str(data_dir)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["assignment"]["seat_id"] == "5-T-01"


def test_whereis_text(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(
        [
            "seats",
            "assign",
            "5-T-01",
            "alice@example.com",
            "--data-dir",
            str(data_dir),
        ]
    )
    capsys.readouterr()
    rc = main(["whereis", "alice@example.com", "--data-dir", str(data_dir)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "5-T-01" in out
