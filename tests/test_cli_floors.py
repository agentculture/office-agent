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


def test_floors_validate_by_id(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Issue #51: passing a floor id (no path) resolves against
    offices.yaml, not as a relative path."""
    rc = main(["floors", "validate", "tlv-floor-5", "--json", "--data-dir", str(data_dir)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    result = payload["results"][0]
    assert result["floor"] == "tlv-floor-5"
    assert result["ok"] is True


def test_floors_doctor_by_id(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`office floors doctor tlv-floor-5 --dry-run` works the same as
    the path form."""
    rc = main(
        [
            "floors",
            "doctor",
            "tlv-floor-5",
            "--dry-run",
            "--json",
            "--data-dir",
            str(data_dir),
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    result = payload["results"][0]
    assert result["floor"] == "tlv-floor-5"
    assert result["dry_run"] is True


def test_floors_validate_path_form_still_works(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Path-form invocations with the .svg suffix don't accidentally
    match a floor id (defensive against future ids that look like paths)."""
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


def test_floors_validate_ambiguous_id_raises(
    data_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Floor id uniqueness is enforced within an office, not globally.
    If two offices declare the same id, the resolver must refuse to pick
    arbitrarily — especially important for `doctor`, which mutates in
    place. Qodo PR-#52 review."""
    # Stage a second office in offices.yaml that re-uses `tlv-floor-5`.
    yaml_path = data_dir / "data" / "offices.yaml"
    appended = yaml_path.read_text(encoding="utf-8") + (
        "\n  - id: dup\n"
        "    name: Duplicate Office\n"
        "    floors:\n"
        "      - id: tlv-floor-5\n"
        "        svg: floors/dup.svg\n"
        "        clusters:\n"
        "          T: { capacity: 1, type: open-space }\n"
    )
    yaml_path.write_text(appended, encoding="utf-8")
    # The dup SVG just needs to exist; content doesn't matter for resolver test.
    (data_dir / "floors" / "dup.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080"/>\n',
        encoding="utf-8",
    )

    rc = main(["floors", "validate", "tlv-floor-5", "--json", "--data-dir", str(data_dir)])
    assert rc != 0
    err = capsys.readouterr().err
    assert "ambiguous" in err
    assert "tlv-floor-5" in err


def test_floors_validate_unknown_id_falls_back_to_path(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Unknown id falls through to path resolution; the resulting error
    is the existing 'not declared in offices.yaml' message — unchanged."""
    rc = main(
        [
            "floors",
            "validate",
            "no-such-floor",
            "--json",
            "--data-dir",
            str(data_dir),
        ]
    )
    assert rc != 0
    err = capsys.readouterr().err
    assert "not declared in offices.yaml" in err


def test_floors_validate_requires_target(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["floors", "validate", "--data-dir", str(data_dir)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "pass an SVG path" in err or "--all" in err


def test_floors_refresh_when_cache_absent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue #54: refresh is idempotent — succeeds even if the cache
    was never created. Operators run it as a precaution."""
    cache = tmp_path / "office-cli" / "drive"
    monkeypatch.setenv("OFFICE_DRIVE_CACHE_DIR", str(cache))
    rc = main(["floors", "refresh", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["removed"] is False
    assert payload["cache_dir"] == str(cache)


def test_floors_refresh_removes_existing_cache(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "office-cli" / "drive"
    (cache / "data").mkdir(parents=True)
    (cache / "data" / "offices.yaml").write_text("offices: []\n", encoding="utf-8")
    monkeypatch.setenv("OFFICE_DRIVE_CACHE_DIR", str(cache))

    rc = main(["floors", "refresh", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["removed"] is True
    assert not cache.exists()


def test_floors_refresh_refuses_unsafe_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Qodo PR #55 review: a mis-set OFFICE_DRIVE_CACHE_DIR (e.g. `/`
    or `$HOME`) must not be silently rmtree'd. The verb requires
    'office-cli' as a path component before deleting anything."""
    danger = tmp_path / "not-our-cache"
    danger.mkdir()
    (danger / "important.txt").write_text("don't lose me", encoding="utf-8")
    monkeypatch.setenv("OFFICE_DRIVE_CACHE_DIR", str(danger))

    rc = main(["floors", "refresh"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "office-cli" in err
    assert "refusing" in err.lower()
    # Untouched.
    assert (danger / "important.txt").is_file()


def test_floors_refresh_surfaces_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Qodo PR #55 review: rmtree errors must not be silently swallowed
    — operators kept serving stale Drive data on failure. Simulate by
    monkeypatching shutil.rmtree to raise."""
    cache = tmp_path / "office-cli" / "drive"
    cache.mkdir(parents=True)
    (cache / "blob").write_text("x", encoding="utf-8")
    monkeypatch.setenv("OFFICE_DRIVE_CACHE_DIR", str(cache))

    def boom(path):
        raise OSError("simulated permission error")

    from office_cli.cli._commands import floors as floors_mod

    monkeypatch.setattr(floors_mod.shutil, "rmtree", boom)
    rc = main(["floors", "refresh"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "failed to remove" in err.lower()


def test_floors_validate_suggests_doctor_on_ctrld_cascade(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Issue #54: when ≥3 seat-id-format errors share a prefix, the
    text output includes a hint pointing at `office floors doctor`.
    The cascade pattern is the operator's most common reason for
    invalid seat ids."""
    polluted = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080">\n'
        # Five Ctrl+D-cascade ids — all share the `5-T-` prefix but
        # fail the seat-id-format regex.
        '<rect id="5-T-06-7-2" class="seat" x="100" y="100" width="51" height="25"/>\n'
        '<rect id="5-T-06-7-4" class="seat" x="160" y="100" width="51" height="25"/>\n'
        '<rect id="5-T-06-7-0" class="seat" x="220" y="100" width="51" height="25"/>\n'
        '<rect id="5-T-06-7-1" class="seat" x="280" y="100" width="51" height="25"/>\n'
        '<rect id="5-T-06-7-3" class="seat" x="340" y="100" width="51" height="25"/>\n'
        "</svg>\n"
    )
    svg_path = data_dir / "floors" / "tlv-floor-5.svg"
    svg_path.write_text(polluted, encoding="utf-8")

    rc = main(["floors", "validate", "tlv-floor-5", "--data-dir", str(data_dir)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "office floors doctor tlv-floor-5" in err
    assert "5-T-" in err


def test_floors_validate_no_doctor_hint_on_clean_file(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Clean files must not get a doctor hint — would be noise."""
    rc = main(["floors", "validate", "tlv-floor-5", "--data-dir", str(data_dir)])
    assert rc == 0
    err = capsys.readouterr().err
    assert "office floors doctor" not in err


def test_floors_validate_doctor_hint_in_json(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """JSON output exposes the same hint via `doctor_hint` so agents
    can branch on it programmatically."""
    polluted = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080">\n'
        '<rect id="5-T-06-7-2" class="seat" x="100" y="100" width="51" height="25"/>\n'
        '<rect id="5-T-06-7-4" class="seat" x="160" y="100" width="51" height="25"/>\n'
        '<rect id="5-T-06-7-0" class="seat" x="220" y="100" width="51" height="25"/>\n'
        "</svg>\n"
    )
    svg_path = data_dir / "floors" / "tlv-floor-5.svg"
    svg_path.write_text(polluted, encoding="utf-8")

    rc = main(["floors", "validate", "tlv-floor-5", "--json", "--data-dir", str(data_dir)])
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    hint = payload["results"][0]["doctor_hint"]
    assert "office floors doctor tlv-floor-5" in hint
