"""Tests for SVG parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from office_cli.cli._errors import OfficeError
from office_cli.floors import parse_svg


def test_parse_good_fixture(fixtures_root: Path) -> None:
    svg = parse_svg(fixtures_root / "floors" / "tlv-floor-5.svg")
    assert svg.view_box == "0 0 1920 1080"
    assert len(svg.seat_ids) == 8
    assert "5-T-01" in svg.seat_ids
    assert svg.room_ids == ("5.18",)
    assert svg.duplicate_ids == ()
    assert svg.untagged_ids == ()


def test_parse_bad_fixture_collects_duplicates(fixtures_root: Path) -> None:
    svg = parse_svg(fixtures_root / "floors" / "tlv-floor-5-bad.svg")
    assert "5-T-02" in svg.duplicate_ids
    assert "5-T-03" in svg.untagged_ids  # missing class="seat"


def test_parse_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(OfficeError) as exc:
        parse_svg(tmp_path / "nope.svg")
    assert exc.value.code == 1


def test_parse_bad_xml_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.svg"
    bad.write_text("<svg><rect", encoding="utf-8")
    with pytest.raises(OfficeError) as exc:
        parse_svg(bad)
    assert exc.value.code == 1
    assert "well-formed" in exc.value.message
