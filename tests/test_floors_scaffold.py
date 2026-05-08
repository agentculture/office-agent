"""Tests for ``office_cli.floors.scaffold_svg`` (the pure module).

The ``_render_pdf_page`` and ``_resolve_page`` helpers shell out to
poppler. We monkeypatch those to keep the unit tests hermetic; CLI-level
tests in ``test_cli_floors.py`` exercise the manifest plumbing the same
way. End-to-end tests against a real PDF live in the repo's smoke-test
runbook (``docs/floor-runbook.md``), not in pytest.
"""

from __future__ import annotations

import base64
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from office_cli.cli._errors import EXIT_USER_ERROR, OfficeError
from office_cli.floors import _scaffold as scaffold_mod
from office_cli.floors import scaffold_svg
from office_cli.offices import load_offices

_FAKE_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"  # minimal PNG header bytes
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
    b"\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01"
    b"5\xcb\xd0\xa6\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _floor(data_dir: Path):
    return load_offices(data_dir)["tlv"].floors["tlv-floor-5"]


def _patch_render(monkeypatch: pytest.MonkeyPatch, png: bytes = _FAKE_PNG) -> None:
    monkeypatch.setattr(scaffold_mod, "_render_pdf_page", lambda *_args, **_kw: png)


def test_scaffold_writes_view_box_and_seat_room(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_render(monkeypatch)
    pdf = data_dir / "fake.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")  # only existence is checked at this layer

    svg_bytes = scaffold_svg(floor=_floor(data_dir), pdf=pdf, page=1)

    root = ET.fromstring(svg_bytes)
    assert root.attrib["viewBox"] == "0 0 1920 1080"
    # Default-namespaced root, not <ns0:svg>
    assert root.tag.endswith("svg")
    assert "{http://www.w3.org/2000/svg}svg" == root.tag

    rects = [el for el in root.iter() if el.tag.endswith("}rect")]
    polys = [el for el in root.iter() if el.tag.endswith("}polygon")]
    assert len(rects) == 1
    assert len(polys) == 1
    seat = rects[0]
    assert seat.get("class") == "seat"
    # tlv-floor-5 declares clusters T and Z; alphabetical sort -> T
    assert seat.get("id") == "5-T-01"
    room = polys[0]
    assert room.get("class") == "room"
    assert room.get("id") == "5.18"  # the only room declared in the fixture


def test_scaffold_embeds_png_as_data_uri(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_render(monkeypatch, png=_FAKE_PNG)
    pdf = data_dir / "fake.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    svg_bytes = scaffold_svg(floor=_floor(data_dir), pdf=pdf, page=1)

    expected_b64 = base64.b64encode(_FAKE_PNG).decode("ascii")
    assert f"data:image/png;base64,{expected_b64}".encode("ascii") in svg_bytes


def test_scaffold_pretty_prints_for_reviewable_diff(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_render(monkeypatch)
    pdf = data_dir / "fake.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    svg_bytes = scaffold_svg(floor=_floor(data_dir), pdf=pdf, page=1)
    text = svg_bytes.decode("utf-8")
    # Multiple newlines (root + image + rect + polygon at minimum)
    assert text.count("\n") >= 4
    # XML decl present
    assert text.startswith("<?xml ")


def test_scaffold_passes_validation_when_floor_status_is_draft(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A scaffold for a `status: draft` floor must validate clean
    (one `floor-draft` warning, zero errors)."""
    from office_cli.floors import parse_svg, validate_floor

    yaml_path = data_dir / "data" / "offices.yaml"
    yaml_path.write_text(
        yaml_path.read_text(encoding="utf-8").replace(
            "      - id: tlv-floor-5",
            "      - id: tlv-floor-5\n        status: draft",
            1,
        ),
        encoding="utf-8",
    )

    _patch_render(monkeypatch)
    pdf = data_dir / "fake.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    svg_bytes = scaffold_svg(floor=_floor(data_dir), pdf=pdf, page=1)
    out = data_dir / "floors" / "tlv-floor-5.svg"
    out.write_bytes(svg_bytes)

    issues = validate_floor(parse_svg(out), _floor(data_dir))
    errors = [i for i in issues if i.severity.value == "error"]
    warnings = [i for i in issues if i.severity.value == "warning"]
    assert errors == []
    assert any(w.rule == "floor-draft" for w in warnings)


def test_scaffold_refuses_floor_without_clusters(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The example seat id needs a cluster letter. A floor with empty
    clusters must error rather than silently produce a malformed SVG."""
    from office_cli.offices._models import Floor

    bare = Floor(
        id="tlv-floor-99",
        svg=data_dir / "floors" / "tlv-floor-99.svg",
        clusters={},
        rooms={},
    )
    pdf = data_dir / "fake.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    with pytest.raises(OfficeError) as exc:
        scaffold_svg(floor=bare, pdf=pdf, page=1)
    assert exc.value.code == EXIT_USER_ERROR
    assert "no clusters" in exc.value.message


def test_scaffold_missing_pdf_raises(data_dir: Path) -> None:
    bogus = data_dir / "no-such.pdf"
    with pytest.raises(OfficeError) as exc:
        scaffold_svg(floor=_floor(data_dir), pdf=bogus, page=1)
    assert exc.value.code == EXIT_USER_ERROR
    assert "PDF not found" in exc.value.message


def test_scaffold_zero_or_negative_page_raises(data_dir: Path) -> None:
    pdf = data_dir / "fake.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    with pytest.raises(OfficeError) as exc:
        scaffold_svg(floor=_floor(data_dir), pdf=pdf, page=0)
    assert exc.value.code == EXIT_USER_ERROR
    assert "1-based" in exc.value.message


def test_resolve_page_label_unique_match(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Label resolution scans pages via pdftotext; one match wins."""
    pdf = data_dir / "fake.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(scaffold_mod, "_pdf_page_count", lambda _p: 3)
    monkeypatch.setattr(
        scaffold_mod,
        "_pdftotext_page",
        lambda _p, n: {1: "cover", 2: "Third Floor plan", 3: "appendix"}[n],
    )
    _patch_render(monkeypatch)

    svg_bytes = scaffold_svg(floor=_floor(data_dir), pdf=pdf, page="Third Floor")
    assert b"<svg " in svg_bytes  # produced something


def test_resolve_page_label_zero_matches_raises(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = data_dir / "fake.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(scaffold_mod, "_pdf_page_count", lambda _p: 2)
    monkeypatch.setattr(scaffold_mod, "_pdftotext_page", lambda _p, _n: "no matching text")

    with pytest.raises(OfficeError) as exc:
        scaffold_svg(floor=_floor(data_dir), pdf=pdf, page="Nonexistent Floor")
    assert "no page" in exc.value.message
    assert "Nonexistent Floor" in exc.value.message


def test_resolve_page_label_multiple_matches_raises(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = data_dir / "fake.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(scaffold_mod, "_pdf_page_count", lambda _p: 2)
    monkeypatch.setattr(scaffold_mod, "_pdftotext_page", lambda _p, _n: "Floor plan")

    with pytest.raises(OfficeError) as exc:
        scaffold_svg(floor=_floor(data_dir), pdf=pdf, page="Floor plan")
    assert "multiple pages" in exc.value.message


def test_scaffold_omits_room_when_floor_has_no_rooms(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A floor declared with `rooms: {}` should produce a scaffold with
    just the example seat — no orphan polygon."""
    from office_cli.offices._models import Cluster, Floor

    pdf = data_dir / "fake.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    _patch_render(monkeypatch)
    floor_no_rooms = Floor(
        id="tlv-floor-7",
        svg=data_dir / "floors" / "tlv-floor-7.svg",
        clusters={"T": Cluster(letter="T", capacity=1)},
        rooms={},
    )

    svg_bytes = scaffold_svg(floor=floor_no_rooms, pdf=pdf, page=1)
    root = ET.fromstring(svg_bytes)
    polys = [el for el in root.iter() if el.tag.endswith("}polygon")]
    assert polys == []
    rects = [el for el in root.iter() if el.tag.endswith("}rect")]
    assert len(rects) == 1
