"""Diagnose-and-fix for floor SVGs.

Cleans up the most common Inkscape pitfall: ``Ctrl+D`` duplication
generates ids like ``5-T-06-7-4-0-8`` and leaves shapes scattered
off-page. :func:`doctor_svg` parses the SVG, drops elements outside
the viewBox, deduplicates near-overlapping shapes, then renumbers
the survivors per the floor's ``offices.yaml`` cluster spec.

The function is pure on the file-system: pass ``dry_run=True`` to
get a report without writing changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET

from office_cli.cli._errors import EXIT_USER_ERROR, OfficeError
from office_cli.offices._models import Floor

_SVG_NS = "{http://www.w3.org/2000/svg}"
_VIEW_W = 1920
_VIEW_H = 1080
_DEDUP_PX = 6.0  # bounding-box centers within this distance treated as duplicates
_ROW_TOL = 30.0  # y-pixel grouping tolerance for row-major spatial sort

# Register namespaces so writes preserve Inkscape's namespace decls.
ET.register_namespace("", "http://www.w3.org/2000/svg")
ET.register_namespace("inkscape", "http://www.inkscape.org/namespaces/inkscape")
ET.register_namespace("sodipodi", "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd")
ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")


@dataclass(frozen=True)
class DoctorReport:
    """Outcome of one :func:`doctor_svg` invocation."""

    floor_id: str
    svg_path: Path
    dry_run: bool
    seats_before: int
    rooms_before: int
    seats_after: int
    rooms_after: int
    actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "floor": self.floor_id,
            "svg": str(self.svg_path),
            "dry_run": self.dry_run,
            "seats_before": self.seats_before,
            "rooms_before": self.rooms_before,
            "seats_after": self.seats_after,
            "rooms_after": self.rooms_after,
            "actions": list(self.actions),
            "warnings": list(self.warnings),
        }


def doctor_svg(svg_path: Path, floor: Floor, *, dry_run: bool = False) -> DoctorReport:
    """Clean up duplicate / off-page noise in ``svg_path`` for ``floor``.

    Steps (in order):

    1. Drop ``<rect class="seat">`` and ``<polygon class="room">``
       elements whose bounding-box center is outside the 1920x1080
       viewBox.
    2. Drop near-duplicate elements (centers within ``_DEDUP_PX`` of
       an already-kept element of the same class).
    3. Sort survivors row-major (y bucketed by ``_ROW_TOL``, then x).
    4. Renumber:
       - seats: walk ``floor.clusters`` in alphabetical order; assign
         ``<floor>-<LETTER>-<NN>`` ids until each cluster's capacity
         is filled. Excess seats beyond the total capacity are dropped.
       - rooms: assign ids from ``floor.rooms`` keys (architect ids)
         in spatial order. Excess rooms are dropped.

    Returns a :class:`DoctorReport` describing what changed. With
    ``dry_run=True`` the file is not written.
    """
    if not svg_path.is_file():
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"SVG not found: {svg_path}",
            remediation="check the path or create the SVG via Inkscape first",
        )

    tree = ET.parse(svg_path)
    root = tree.getroot()
    parents = {child: parent for parent in root.iter() for child in parent}

    seats = [
        el
        for el in root.iter()
        if el.tag == f"{_SVG_NS}rect" and (el.get("class") or "").strip() == "seat"
    ]
    rooms = [
        el
        for el in root.iter()
        if el.tag == f"{_SVG_NS}polygon" and (el.get("class") or "").strip() == "room"
    ]
    seats_before = len(seats)
    rooms_before = len(rooms)

    actions: list[str] = []
    warnings: list[str] = []

    seats, dropped = _drop_off_page(seats, parents)
    if dropped:
        actions.append(f"dropped {dropped} off-page seats")
    rooms, dropped = _drop_off_page(rooms, parents)
    if dropped:
        actions.append(f"dropped {dropped} off-page rooms")

    seats, dropped = _dedupe(seats, parents)
    if dropped:
        actions.append(f"dropped {dropped} near-duplicate seats")
    rooms, dropped = _dedupe(rooms, parents)
    if dropped:
        actions.append(f"dropped {dropped} near-duplicate rooms")

    floor_num = floor.number
    seat_slots = _seat_ids_for(floor_num, floor.clusters)
    cluster_total = len(seat_slots)
    seat_renamed, seat_excess = _assign_ids(seats, seat_slots, parents)
    if seat_renamed:
        actions.append(f"renamed {seat_renamed} seats")
    if seat_excess:
        actions.append(f"dropped {seat_excess} excess seats")

    room_slots = list(floor.rooms.keys())
    room_renamed, room_excess = _assign_ids(rooms, room_slots, parents)
    if room_renamed:
        actions.append(f"renamed {room_renamed} rooms")
    if room_excess:
        actions.append(f"dropped {room_excess} excess rooms")

    seats_after = min(len(seats) - seat_excess, cluster_total)
    rooms_after = min(len(rooms) - room_excess, len(room_slots))

    if seats_after < cluster_total:
        warnings.append(
            f"{seats_after} seats traced; offices.yaml declares {cluster_total} "
            "(trace more in Inkscape and re-run)"
        )
    if rooms_after < len(room_slots):
        warnings.append(
            f"{rooms_after} rooms traced; offices.yaml declares {len(room_slots)} "
            "(trace more in Inkscape and re-run)"
        )

    if not dry_run and actions:
        tree.write(svg_path, encoding="utf-8", xml_declaration=True)

    return DoctorReport(
        floor_id=floor.id,
        svg_path=svg_path,
        dry_run=dry_run,
        seats_before=seats_before,
        rooms_before=rooms_before,
        seats_after=seats_after,
        rooms_after=rooms_after,
        actions=actions,
        warnings=warnings,
    )


# -- helpers ----------------------------------------------------------------


def _assign_ids(
    elements: list[ET.Element],
    slots: list[str],
    parents: dict[ET.Element, ET.Element],
) -> tuple[int, int]:
    """Assign ids in ``slots`` to ``elements`` while preserving valid ones.

    Walks ``elements`` in two passes:

    1. **Keep pass**: any element whose current id is already a valid
       slot (and not yet claimed by another) keeps its id unchanged.
    2. **Renumber pass**: remaining elements are sorted spatially and
       assigned the leftover slots in order.

    Elements with no slot to assign (more elements than slots) are
    removed from the tree. Returns ``(renamed, excess_dropped)``.
    """
    slot_set = set(slots)
    kept: set[int] = set()
    used: set[str] = set()
    for i, el in enumerate(elements):
        sid = (el.get("id") or "").strip()
        if sid in slot_set and sid not in used:
            kept.add(i)
            used.add(sid)

    to_rename = [(i, el) for i, el in enumerate(elements) if i not in kept]
    to_rename.sort(key=lambda pair: _spatial_key(pair[1]))

    available = [s for s in slots if s not in used]

    renamed = 0
    for (_, el), new_id in zip(to_rename, available):
        if el.get("id") != new_id:
            renamed += 1
        el.set("id", new_id)

    excess = to_rename[len(available) :]
    for _, el in excess:
        _remove(el, parents)

    return renamed, len(excess)


def _seat_ids_for(floor_num: str, clusters) -> list[str]:
    """Walk clusters in alphabetical order and emit their full seat ids."""
    out: list[str] = []
    for letter in sorted(clusters.keys()):
        cluster = clusters[letter]
        for n in range(1, cluster.capacity + 1):
            out.append(f"{floor_num}-{letter}-{n:02d}")
    return out


def _center(el: ET.Element) -> tuple[float, float]:
    if el.tag == f"{_SVG_NS}rect":
        x = float(el.get("x", 0))
        y = float(el.get("y", 0))
        w = float(el.get("width", 0))
        h = float(el.get("height", 0))
        return (x + w / 2, y + h / 2)
    if el.tag == f"{_SVG_NS}polygon":
        pts = el.get("points", "")
        nums = [float(c) for c in re.split(r"[\s,]+", pts.strip()) if c]
        if not nums:
            return (0.0, 0.0)
        xs = nums[0::2]
        ys = nums[1::2]
        return (sum(xs) / len(xs), sum(ys) / len(ys))
    return (0.0, 0.0)


def _spatial_key(el: ET.Element) -> tuple[float, float]:
    cx, cy = _center(el)
    return (round(cy / _ROW_TOL), cx)


def _in_viewbox(cx: float, cy: float) -> bool:
    return 0 <= cx <= _VIEW_W and 0 <= cy <= _VIEW_H


def _drop_off_page(
    items: list[ET.Element], parents: dict[ET.Element, ET.Element]
) -> tuple[list[ET.Element], int]:
    kept: list[ET.Element] = []
    dropped = 0
    for el in items:
        cx, cy = _center(el)
        if _in_viewbox(cx, cy):
            kept.append(el)
        else:
            _remove(el, parents)
            dropped += 1
    return kept, dropped


def _dedupe(
    items: list[ET.Element], parents: dict[ET.Element, ET.Element]
) -> tuple[list[ET.Element], int]:
    kept: list[ET.Element] = []
    kept_centers: list[tuple[float, float]] = []
    dropped = 0
    for el in items:
        c = _center(el)
        if any(_dist(c, kc) < _DEDUP_PX for kc in kept_centers):
            _remove(el, parents)
            dropped += 1
        else:
            kept.append(el)
            kept_centers.append(c)
    return kept, dropped


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _remove(el: ET.Element, parents: dict[ET.Element, ET.Element]) -> None:
    parent = parents.get(el)
    if parent is not None:
        parent.remove(el)


def _all_elements(items: Iterable[ET.Element]) -> list[ET.Element]:
    return list(items)
