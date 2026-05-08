"""Tests for ``office floors doctor`` cleanup logic."""

from __future__ import annotations

from pathlib import Path

import pytest

from office_cli.cli._errors import EXIT_USER_ERROR, OfficeError
from office_cli.floors import doctor_svg, parse_svg, validate_floor
from office_cli.offices import load_offices


def _floor(data_dir: Path):
    return load_offices(data_dir)["tlv"].floors["tlv-floor-5"]


def _polluted_svg(view_box: str = "0 0 1920 1080") -> str:
    """Return an SVG mimicking the Inkscape Ctrl+D cascade we saw in the wild.

    21 seats (5 on-page, 16 off-page above) and 14 rooms (all stacked
    duplicates near 1500,400). All seats have garbled
    ``5-T-06-7-4-...`` ids; all rooms have ``5.18-...`` ids.
    """
    on_page_seats = [
        # Row 1 (top)
        ("5-T-06-7-2", 92.99, 73.25),
        ("5-T-06-7-0", 145.04, 75.10),
        # Row 2 (bottom)
        ("5-T-06", 41.80, 102.08),
        ("5-T-06-7", 93.05, 101.54),
        ("5-T-06-7-4", 143.73, 102.45),
    ]
    off_page_seats = [(f"5-T-06-extra-{i}", 50 + (i * 3 % 100), -300 - i * 8) for i in range(16)]
    seat_lines = []
    for sid, x, y in on_page_seats + off_page_seats:
        seat_lines.append(f'<rect id="{sid}" class="seat" x="{x}" y="{y}" width="51" height="25"/>')

    # 14 rooms all at roughly the same location → all duplicates.
    room_lines = []
    for i in range(14):
        offset = i * 0.5  # centers all within ~7 px → dedupe will catch them
        rid = "5.18" if i == 0 else f"5.18-{'-'.join(str(d) for d in range(1, i + 1))}"
        pts = (
            f"{1400 + offset},{300 + offset} "
            f"{1700 + offset},{300 + offset} "
            f"{1700 + offset},{500 + offset} "
            f"{1400 + offset},{500 + offset}"
        )
        room_lines.append(f'<polygon id="{rid}" class="room" points="{pts}"/>')

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view_box}">\n'
        + "\n".join(seat_lines)
        + "\n"
        + "\n".join(room_lines)
        + "\n</svg>\n"
    )


def test_doctor_drops_off_page_and_dedupes_rooms(data_dir: Path) -> None:
    svg_path = data_dir / "floors" / "tlv-floor-5.svg"
    svg_path.write_text(_polluted_svg(), encoding="utf-8")

    report = doctor_svg(svg_path, _floor(data_dir))

    assert report.seats_before == 21
    assert report.rooms_before == 14
    assert report.seats_after == 5  # five on-page seats survived
    assert report.rooms_after == 1
    assert any("off-page seats" in a for a in report.actions)
    assert any("near-duplicate rooms" in a for a in report.actions)


def test_doctor_renumbers_in_spatial_order(data_dir: Path) -> None:
    svg_path = data_dir / "floors" / "tlv-floor-5.svg"
    svg_path.write_text(_polluted_svg(), encoding="utf-8")

    doctor_svg(svg_path, _floor(data_dir))

    # The five survivors get cluster T slots. One of the polluted
    # ids (`5-T-06`) was already a valid slot, so the doctor preserves
    # it and assigns the remaining four to spatially-ordered slots.
    svg = parse_svg(svg_path)
    assert sorted(svg.seat_ids) == ["5-T-01", "5-T-02", "5-T-03", "5-T-04", "5-T-06"]
    assert sorted(svg.room_ids) == ["5.18"]


def test_doctor_makes_validate_clean(data_dir: Path) -> None:
    svg_path = data_dir / "floors" / "tlv-floor-5.svg"
    svg_path.write_text(_polluted_svg(), encoding="utf-8")

    doctor_svg(svg_path, _floor(data_dir))

    svg = parse_svg(svg_path)
    issues = validate_floor(svg, _floor(data_dir))
    errors = [i for i in issues if i.severity.value == "error"]
    assert errors == []


def test_doctor_dry_run_reports_without_writing(data_dir: Path) -> None:
    svg_path = data_dir / "floors" / "tlv-floor-5.svg"
    polluted = _polluted_svg()
    svg_path.write_text(polluted, encoding="utf-8")

    report = doctor_svg(svg_path, _floor(data_dir), dry_run=True)

    assert report.dry_run is True
    assert report.seats_after == 5
    # File on disk is unchanged.
    assert svg_path.read_text(encoding="utf-8") == polluted


def test_doctor_warns_when_capacity_short(data_dir: Path) -> None:
    """offices.yaml declares 6+2=8 seats; polluted fixture has 5
    on-page survivors. Doctor should still succeed but emit a warning
    so the operator knows to trace more in Inkscape."""
    svg_path = data_dir / "floors" / "tlv-floor-5.svg"
    svg_path.write_text(_polluted_svg(), encoding="utf-8")

    report = doctor_svg(svg_path, _floor(data_dir))

    assert any("5 seats traced" in w for w in report.warnings)
    assert any("declares 8" in w for w in report.warnings)


def test_doctor_drops_excess_seats_beyond_capacity(data_dir: Path) -> None:
    """An SVG with more on-page seats than the cluster total should
    have the excess deleted, not left to fail validation later."""
    extras = "".join(
        f'<rect id="extra-{i}" class="seat" x="{200 + i * 60}" y="800" width="40" height="20"/>'
        for i in range(15)  # 15 extra seats > total capacity 8
    )
    svg_text = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080">\n'
        + extras
        + '<polygon id="r" class="room" points="1400,300 1700,300 1700,500 1400,500"/>\n'
        + "</svg>\n"
    )
    svg_path = data_dir / "floors" / "tlv-floor-5.svg"
    svg_path.write_text(svg_text, encoding="utf-8")

    report = doctor_svg(svg_path, _floor(data_dir))

    assert report.seats_before == 15
    assert report.seats_after == 8  # T:6 + Z:2
    assert any("excess seats" in a for a in report.actions)


def test_doctor_idempotent_on_clean_file(data_dir: Path) -> None:
    svg_path = data_dir / "floors" / "tlv-floor-5.svg"
    before = svg_path.read_text(encoding="utf-8")

    report = doctor_svg(svg_path, _floor(data_dir))

    after = svg_path.read_text(encoding="utf-8")
    # The fixture is already clean (8 seats matching cluster spec, 1 room).
    # Doctor should produce no actions and not rewrite the file.
    assert report.actions == []
    assert before == after


def test_doctor_missing_file_raises(data_dir: Path) -> None:
    bogus = data_dir / "floors" / "no-such.svg"
    with pytest.raises(OfficeError) as exc:
        doctor_svg(bogus, _floor(data_dir))
    assert exc.value.code == EXIT_USER_ERROR


def test_doctor_malformed_xml_raises_office_error(data_dir: Path) -> None:
    """A malformed SVG must surface as ``OfficeError``, not a raw
    ``ET.ParseError`` traceback (consistent with ``parse_svg``)."""
    svg_path = data_dir / "floors" / "tlv-floor-5.svg"
    svg_path.write_text("<svg><rect class='seat' id='oops'</svg>\n", encoding="utf-8")
    with pytest.raises(OfficeError) as exc:
        doctor_svg(svg_path, _floor(data_dir))
    assert exc.value.code == EXIT_USER_ERROR
    assert "well-formed" in exc.value.message.lower()


def test_doctor_writes_browser_compatible_svg_root(data_dir: Path) -> None:
    """Regression: doctor must emit `<svg xmlns="...">` (default
    namespace), not `<ns0:svg xmlns:ns0="...">`. Browsers reject the
    prefixed-root form even though the XML is well-formed."""
    svg_path = data_dir / "floors" / "tlv-floor-5.svg"
    polluted = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080">'
        '<rect id="g1" class="seat" x="100" y="100" width="40" height="40"/>'
        '<rect id="off" class="seat" x="100" y="-500" width="40" height="40"/>'
        '<polygon id="r" class="room" points="1400,300 1700,300 1700,500 1400,500"/>'
        "</svg>\n"
    )
    svg_path.write_text(polluted, encoding="utf-8")

    doctor_svg(svg_path, _floor(data_dir))

    written = svg_path.read_text(encoding="utf-8")
    # Root must be bare `<svg`, not `<ns0:svg`. Allow a leading XML decl.
    assert "<ns0:svg" not in written
    assert "<svg " in written
    # And the SVG namespace must be the default xmlns.
    assert 'xmlns="http://www.w3.org/2000/svg"' in written


def test_doctor_pretty_prints_output(data_dir: Path) -> None:
    """Issue #54: doctor's output must be human-readable in `git diff`,
    not a single minified line. The result has at least one newline
    between elements, while still keeping the bare `<svg ` root."""
    svg_path = data_dir / "floors" / "tlv-floor-5.svg"
    svg_path.write_text(_polluted_svg(), encoding="utf-8")

    doctor_svg(svg_path, _floor(data_dir))

    written = svg_path.read_text(encoding="utf-8")
    # More than just the XML decl + one giant element — needs internal
    # newlines so the file diffs cleanly.
    assert written.count("\n") > 5
    # Root must still be the default-namespaced bare <svg> form.
    assert "<svg " in written
    assert "<ns0:svg" not in written


def test_doctor_polygon_with_malformed_points_does_not_crash(
    data_dir: Path,
) -> None:
    """Polygons with empty or odd ``points`` must not raise
    ZeroDivisionError; the doctor treats them as off-page outliers
    and drops them."""
    svg_text = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080">'
        # Empty points → center returns (0,0); inside the viewBox top-left
        # but functionally a "bad" room. doctor still must not crash.
        '<polygon id="empty" class="room" points=""/>'
        # Single number (odd token count) → also handled.
        '<polygon id="single" class="room" points="50"/>'
        # A real, valid room.
        '<polygon id="ok" class="room" points="1400,300 1700,300 1700,500 1400,500"/>'
        "</svg>\n"
    )
    svg_path = data_dir / "floors" / "tlv-floor-5.svg"
    svg_path.write_text(svg_text, encoding="utf-8")

    report = doctor_svg(svg_path, _floor(data_dir))
    # Doctor completed; the valid room got the slot.
    assert report.rooms_after == 1
