"""Tests for SVG-vs-YAML validation."""

from __future__ import annotations

from pathlib import Path

from office_cli.floors import Severity, parse_svg, validate_floor
from office_cli.offices import load_offices


def _floor(data_dir: Path):
    return load_offices(data_dir)["tlv"].floors["tlv-floor-5"]


def test_good_fixture_has_no_errors(data_dir: Path) -> None:
    svg = parse_svg(data_dir / "floors" / "tlv-floor-5.svg")
    issues = validate_floor(svg, _floor(data_dir))
    assert [i for i in issues if i.severity is Severity.ERROR] == []


def test_bad_fixture_reports_each_rule(data_dir: Path, fixtures_root: Path) -> None:
    bad_path = fixtures_root / "floors" / "tlv-floor-5-bad.svg"
    svg = parse_svg(bad_path)
    issues = validate_floor(svg, _floor(data_dir))
    rules = {i.rule for i in issues}
    # Each of these rule violations is present in the bad fixture.
    assert "view-box" in rules
    assert "duplicate-id" in rules
    assert "seat-floor-mismatch" in rules
    assert "seat-id-format" in rules
    assert "unknown-cluster" in rules
    assert "missing-class" in rules
    assert "room-id-format" in rules


def test_warnings_do_not_block(data_dir: Path) -> None:
    # Drop one seat from the SVG so the cluster-capacity check warns.
    svg_path = data_dir / "floors" / "tlv-floor-5.svg"
    text = svg_path.read_text(encoding="utf-8").replace(
        '<rect id="5-T-06" class="seat" x="240" y="160" width="40" height="60"/>',
        "",
    )
    svg_path.write_text(text, encoding="utf-8")
    svg = parse_svg(svg_path)
    issues = validate_floor(svg, _floor(data_dir))
    severities = {i.severity for i in issues}
    assert Severity.ERROR not in severities
    assert Severity.WARNING in severities
