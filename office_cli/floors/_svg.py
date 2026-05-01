"""Parse a floor SVG into a structured view.

Reads only what the agent contract promises: ``<rect>`` / ``<polygon>``
elements with an ``id`` attribute, optionally tagged with
``class="seat"`` / ``class="room"``. Everything else (background image,
layer groups, styles) is ignored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

from office_cli.cli._errors import EXIT_USER_ERROR, OfficeError

_SVG_NS = "{http://www.w3.org/2000/svg}"


@dataclass(frozen=True)
class FloorSvg:
    path: Path
    view_box: str
    seat_ids: tuple[str, ...] = field(default_factory=tuple)
    room_ids: tuple[str, ...] = field(default_factory=tuple)
    untagged_ids: tuple[str, ...] = field(default_factory=tuple)
    duplicate_ids: tuple[str, ...] = field(default_factory=tuple)


def parse_svg(path: Path) -> FloorSvg:
    root = _load_root(path)
    seats: list[str] = []
    rooms: list[str] = []
    untagged: list[str] = []
    seen: set[str] = set()
    dup: list[str] = []
    for tag in ("rect", "polygon"):
        for el in root.iter(f"{_SVG_NS}{tag}"):
            _classify(el, seats, rooms, untagged, seen, dup)
    return FloorSvg(
        path=path,
        view_box=root.attrib.get("viewBox", ""),
        seat_ids=tuple(seats),
        room_ids=tuple(rooms),
        untagged_ids=tuple(untagged),
        duplicate_ids=tuple(dup),
    )


def _load_root(path: Path) -> ET.Element:
    if not path.is_file():
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"SVG not found: {path}",
            remediation="check the path or run from the repo root",
        )
    try:
        return ET.parse(path).getroot()
    except ET.ParseError as err:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"SVG is not well-formed XML: {path}: {err}",
            remediation="open in Inkscape and re-save as Plain SVG",
        ) from err


_BUCKETS = {"seat": 0, "room": 1}  # → index into the (seats, rooms, untagged) tuple


def _classify(
    el: ET.Element,
    seats: list[str],
    rooms: list[str],
    untagged: list[str],
    seen: set[str],
    dup: list[str],
) -> None:
    sid = el.attrib.get("id")
    if not sid:
        return
    if sid in seen:
        dup.append(sid)
    else:
        seen.add(sid)
    cls = (el.attrib.get("class") or "").strip()
    bucket = (seats, rooms, untagged)[_BUCKETS.get(cls, 2)]
    bucket.append(sid)
