"""Tests for ``office_cli.floors.copy_layout`` (the pure module)."""

from __future__ import annotations

from pathlib import Path

import pytest

from office_cli.cli._errors import EXIT_USER_ERROR, OfficeError
from office_cli.floors import copy_layout, parse_svg
from office_cli.offices._models import Cluster, Floor, Room


def _src_svg() -> str:
    """A clean floor-5 stencil: 6 T-cluster seats + 2 Z-cluster seats + 1 room."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080">\n'
        # Six T seats arranged in two rows.
        '<rect id="5-T-01" class="seat" x="100" y="100" width="51" height="25"/>\n'
        '<rect id="5-T-02" class="seat" x="160" y="100" width="51" height="25"/>\n'
        '<rect id="5-T-03" class="seat" x="220" y="100" width="51" height="25"/>\n'
        '<rect id="5-T-04" class="seat" x="100" y="200" width="51" height="25"/>\n'
        '<rect id="5-T-05" class="seat" x="160" y="200" width="51" height="25"/>\n'
        '<rect id="5-T-06" class="seat" x="220" y="200" width="51" height="25"/>\n'
        # Two Z phone-room seats.
        '<rect id="5-Z-01" class="seat" x="500" y="500" width="51" height="25"/>\n'
        '<rect id="5-Z-02" class="seat" x="560" y="500" width="51" height="25"/>\n'
        # One named room.
        '<polygon id="5.18" class="room" points="800,300 1000,300 1000,500 800,500"/>\n'
        "</svg>\n"
    )


def _dst_scaffold(floor_num: str = "3") -> str:
    """A scaffold-shaped SVG: embedded background + 1 example seat + 1 example room."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080"'
        ' width="1920" height="1080">\n'
        # Background image (preserved across copy).
        '<image x="0" y="0" width="1920" height="1080" href="data:image/png;base64,FAKE"/>\n'
        # Example placeholders (should be replaced).
        f'<rect id="{floor_num}-T-01" class="seat" x="100" y="100" width="51" height="25"/>\n'
        '<polygon id="placeholder-room" class="room" points="200,200 260,200 260,240 200,240"/>\n'
        "</svg>\n"
    )


def _src_floor() -> Floor:
    return Floor(
        id="tlv-floor-5",
        svg=Path("/dev/null"),
        clusters={
            "T": Cluster(letter="T", capacity=6),
            "Z": Cluster(letter="Z", capacity=2, type="phone-room"),
        },
        rooms={"5.18": Room(id="5.18", name="MR")},
        status="active",
    )


def _dst_floor(status: str = "draft") -> Floor:
    return Floor(
        id="tlv-floor-3",
        svg=Path("/dev/null"),
        clusters={
            "T": Cluster(letter="T", capacity=6),
            "Z": Cluster(letter="Z", capacity=2, type="phone-room"),
        },
        rooms={"3.10": Room(id="3.10", name="Conf 3.10")},
        status=status,
    )


def test_copy_layout_renumbers_per_dst_spec(tmp_path: Path) -> None:
    src = tmp_path / "src.svg"
    src.write_text(_src_svg(), encoding="utf-8")
    dst = tmp_path / "dst.svg"
    dst.write_text(_dst_scaffold(), encoding="utf-8")

    report = copy_layout(
        src_path=src,
        src_floor=_src_floor(),
        dst_path=dst,
        dst_floor=_dst_floor(),
    )

    assert report.seats_copied == 8  # 6 T + 2 Z
    assert report.rooms_copied == 1
    parsed = parse_svg(dst)
    assert sorted(parsed.seat_ids) == [
        "3-T-01",
        "3-T-02",
        "3-T-03",
        "3-T-04",
        "3-T-05",
        "3-T-06",
        "3-Z-01",
        "3-Z-02",
    ]
    assert sorted(parsed.room_ids) == ["3.10"]


def test_copy_layout_preserves_dst_background(tmp_path: Path) -> None:
    """The embedded ``<image>`` must survive the copy untouched."""
    src = tmp_path / "src.svg"
    src.write_text(_src_svg(), encoding="utf-8")
    dst = tmp_path / "dst.svg"
    dst.write_text(_dst_scaffold(), encoding="utf-8")

    copy_layout(
        src_path=src,
        src_floor=_src_floor(),
        dst_path=dst,
        dst_floor=_dst_floor(),
    )

    written = dst.read_text(encoding="utf-8")
    assert 'href="data:image/png;base64,FAKE"' in written


def test_copy_layout_preserves_seat_geometry(tmp_path: Path) -> None:
    """Seat ``x/y/w/h`` come over verbatim — only the id changes."""
    src = tmp_path / "src.svg"
    src.write_text(_src_svg(), encoding="utf-8")
    dst = tmp_path / "dst.svg"
    dst.write_text(_dst_scaffold(), encoding="utf-8")

    copy_layout(
        src_path=src,
        src_floor=_src_floor(),
        dst_path=dst,
        dst_floor=_dst_floor(),
    )

    written = dst.read_text(encoding="utf-8")
    # First src seat was at (100, 100); after spatial sort + reassign it
    # becomes 3-T-01 at the same x/y.
    assert 'id="3-T-01"' in written
    assert 'x="100"' in written
    assert 'y="100"' in written


def test_copy_layout_emits_browser_compatible_root(tmp_path: Path) -> None:
    """No <ns0:svg> regression — same constraint as doctor + scaffold."""
    src = tmp_path / "src.svg"
    src.write_text(_src_svg(), encoding="utf-8")
    dst = tmp_path / "dst.svg"
    dst.write_text(_dst_scaffold(), encoding="utf-8")

    copy_layout(
        src_path=src,
        src_floor=_src_floor(),
        dst_path=dst,
        dst_floor=_dst_floor(),
    )

    written = dst.read_text(encoding="utf-8")
    assert "<ns0:svg" not in written
    assert "<svg " in written


def test_copy_layout_drops_existing_dst_seats(tmp_path: Path) -> None:
    """The dst's example placeholders must be gone after the copy."""
    src = tmp_path / "src.svg"
    src.write_text(_src_svg(), encoding="utf-8")
    dst = tmp_path / "dst.svg"
    dst.write_text(_dst_scaffold(), encoding="utf-8")

    copy_layout(
        src_path=src,
        src_floor=_src_floor(),
        dst_path=dst,
        dst_floor=_dst_floor(),
    )

    parsed = parse_svg(dst)
    # `placeholder-room` from the scaffold must NOT survive — the room
    # got either renamed (to 3.10) or dropped.
    assert "placeholder-room" not in parsed.room_ids


def test_copy_layout_capacity_warning_when_dst_smaller(tmp_path: Path) -> None:
    """Dst declares fewer seats than src has → excess dropped + warning."""
    src = tmp_path / "src.svg"
    src.write_text(_src_svg(), encoding="utf-8")
    dst = tmp_path / "dst.svg"
    dst.write_text(_dst_scaffold(), encoding="utf-8")

    small_dst = Floor(
        id="tlv-floor-3",
        svg=Path("/dev/null"),
        clusters={"T": Cluster(letter="T", capacity=2)},
        rooms={},
        status="draft",
    )
    report = copy_layout(
        src_path=src,
        src_floor=_src_floor(),
        dst_path=dst,
        dst_floor=small_dst,
    )

    # 8 seats from src, dst has T:2 = 2 slots → 6 dropped
    assert report.seats_copied == 2
    assert any("dropped 6 excess seats" in a for a in report.actions)


def test_copy_layout_refuses_active_dst_without_overwrite(tmp_path: Path) -> None:
    src = tmp_path / "src.svg"
    src.write_text(_src_svg(), encoding="utf-8")
    dst = tmp_path / "dst.svg"
    dst.write_text(_dst_scaffold(), encoding="utf-8")

    with pytest.raises(OfficeError) as exc:
        copy_layout(
            src_path=src,
            src_floor=_src_floor(),
            dst_path=dst,
            dst_floor=_dst_floor(status="active"),
        )
    assert exc.value.code == EXIT_USER_ERROR
    assert "refusing to clobber" in exc.value.message


def test_copy_layout_overwrite_flag_allows_active_dst(tmp_path: Path) -> None:
    src = tmp_path / "src.svg"
    src.write_text(_src_svg(), encoding="utf-8")
    dst = tmp_path / "dst.svg"
    dst.write_text(_dst_scaffold(), encoding="utf-8")

    report = copy_layout(
        src_path=src,
        src_floor=_src_floor(),
        dst_path=dst,
        dst_floor=_dst_floor(status="active"),
        overwrite=True,
    )
    assert report.seats_copied == 8


def test_copy_layout_refuses_src_with_validation_errors(tmp_path: Path) -> None:
    """Don't propagate broken layouts."""
    bad_src = tmp_path / "src.svg"
    bad_src.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080">\n'
        # Garbled id — will fail seat-id-format
        '<rect id="garbage-seat" class="seat" x="100" y="100" width="51" height="25"/>\n'
        "</svg>\n",
        encoding="utf-8",
    )
    dst = tmp_path / "dst.svg"
    dst.write_text(_dst_scaffold(), encoding="utf-8")

    with pytest.raises(OfficeError) as exc:
        copy_layout(
            src_path=bad_src,
            src_floor=_src_floor(),
            dst_path=dst,
            dst_floor=_dst_floor(),
        )
    assert "validation" in exc.value.message


def test_copy_layout_missing_paths_raise(tmp_path: Path) -> None:
    bogus = tmp_path / "missing.svg"
    real = tmp_path / "real.svg"
    real.write_text(_src_svg(), encoding="utf-8")

    with pytest.raises(OfficeError) as exc1:
        copy_layout(
            src_path=bogus,
            src_floor=_src_floor(),
            dst_path=real,
            dst_floor=_dst_floor(),
        )
    assert "src SVG not found" in exc1.value.message

    with pytest.raises(OfficeError) as exc2:
        copy_layout(
            src_path=real,
            src_floor=_src_floor(),
            dst_path=bogus,
            dst_floor=_dst_floor(),
        )
    assert "dst SVG not found" in exc2.value.message
