"""End-to-end tests for ``office floors`` commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from office_cli.cli import main


def test_floors_list_text(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["floors", "list", "--data-dir", str(data_dir)]) == 0
    out = capsys.readouterr().out
    assert "tlv-floor-5" in out


def test_floors_list_json(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["floors", "list", "--json", "--data-dir", str(data_dir)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["floors"]) == 1
    floor = payload["floors"][0]
    assert floor["floor"] == "tlv-floor-5"
    assert floor["clusters"] == {"T": 6, "Z": 2}


def test_floors_validate_good(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    svg = data_dir / "floors" / "tlv-floor-5.svg"
    rc = main(["floors", "validate", str(svg), "--json", "--data-dir", str(data_dir)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["ok"] is True


def test_floors_validate_bad(
    data_dir: Path, fixtures_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = data_dir / "floors" / "tlv-floor-5.svg"
    bad.write_text(
        (fixtures_root / "floors" / "tlv-floor-5-bad.svg").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    rc = main(["floors", "validate", str(bad), "--json", "--data-dir", str(data_dir)])
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    result = payload["results"][0]
    assert result["ok"] is False
    assert result["errors"]


def test_floors_validate_requires_target(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["floors", "validate", "--data-dir", str(data_dir)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "pass an SVG path" in err or "--all" in err
