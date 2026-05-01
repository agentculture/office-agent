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


def test_whereis_as_of_filters(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(
        [
            "seats",
            "assign",
            "5-T-01",
            "alice@example.com",
            "--from",
            "2026-07-01",
            "--data-dir",
            str(data_dir),
        ]
    )
    capsys.readouterr()
    # Before the effective window: no seat.
    rc = main(
        [
            "whereis",
            "alice@example.com",
            "--as-of",
            "2026-06-01",
            "--json",
            "--data-dir",
            str(data_dir),
        ]
    )
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["assignment"] is None
    # Inside the window: the row.
    rc = main(
        [
            "whereis",
            "alice@example.com",
            "--as-of",
            "2026-07-15",
            "--json",
            "--data-dir",
            str(data_dir),
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["assignment"]["seat_id"] == "5-T-01"


def test_whereis_rejects_malformed_as_of(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        [
            "whereis",
            "alice@example.com",
            "--as-of",
            "yesterday",
            "--data-dir",
            str(data_dir),
        ]
    )
    assert rc == 1
    assert "--as-of" in capsys.readouterr().err
