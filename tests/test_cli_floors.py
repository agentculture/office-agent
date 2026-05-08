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


def test_floors_validate_relative_path_from_other_cwd(
    data_dir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Relative SVG path must resolve against --data-dir, not cwd. Qodo #6."""
    other = data_dir.parent / "elsewhere"
    other.mkdir()
    monkeypatch.chdir(other)
    rc = main(
        [
            "floors",
            "validate",
            "floors/tlv-floor-5.svg",
            "--json",
            "--data-dir",
            str(data_dir),
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["ok"] is True


def test_floors_doctor_dry_run_reports(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Polluted SVG → dry-run reports actions but doesn't write."""
    svg = data_dir / "floors" / "tlv-floor-5.svg"
    polluted = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080">'
        '<rect id="garbled-1" class="seat" x="100" y="100" width="40" height="40"/>'
        '<rect id="garbled-2" class="seat" x="200" y="100" width="40" height="40"/>'
        '<rect id="off-page" class="seat" x="100" y="-500" width="40" height="40"/>'
        '<polygon id="r1" class="room" points="1400,300 1700,300 1700,500 1400,500"/>'
        '<polygon id="r2" class="room" points="1401,301 1701,301 1701,501 1401,501"/>'
        "</svg>\n"
    )
    before = polluted
    svg.write_text(polluted, encoding="utf-8")

    rc = main(
        [
            "floors",
            "doctor",
            str(svg),
            "--dry-run",
            "--json",
            "--data-dir",
            str(data_dir),
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    result = payload["results"][0]
    assert result["dry_run"] is True
    assert result["seats_before"] == 3
    assert result["seats_after"] == 2
    assert result["rooms_before"] == 2
    assert result["rooms_after"] == 1
    # No write happened.
    assert svg.read_text(encoding="utf-8") == before


def test_floors_doctor_writes_and_validate_passes(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Doctor writes the cleaned SVG; subsequent validate is clean."""
    svg = data_dir / "floors" / "tlv-floor-5.svg"
    polluted = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080">'
        '<rect id="g1" class="seat" x="100" y="100" width="40" height="40"/>'
        '<rect id="g2" class="seat" x="200" y="100" width="40" height="40"/>'
        '<rect id="g3" class="seat" x="300" y="100" width="40" height="40"/>'
        '<rect id="g4" class="seat" x="400" y="100" width="40" height="40"/>'
        '<rect id="g5" class="seat" x="500" y="100" width="40" height="40"/>'
        '<rect id="g6" class="seat" x="600" y="100" width="40" height="40"/>'
        '<rect id="g7" class="seat" x="700" y="100" width="40" height="40"/>'
        '<rect id="g8" class="seat" x="800" y="100" width="40" height="40"/>'
        '<polygon id="r1" class="room" points="1400,300 1700,300 1700,500 1400,500"/>'
        "</svg>\n"
    )
    svg.write_text(polluted, encoding="utf-8")

    rc = main(["floors", "doctor", str(svg), "--data-dir", str(data_dir)])
    assert rc == 0
    capsys.readouterr()  # drain doctor output

    rc = main(["floors", "validate", str(svg), "--json", "--data-dir", str(data_dir)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    result = payload["results"][0]
    assert result["ok"] is True
    assert result["errors"] == []


def test_floors_validate_requires_target(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["floors", "validate", "--data-dir", str(data_dir)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "pass an SVG path" in err or "--all" in err
