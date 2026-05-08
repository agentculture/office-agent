"""Diagnose-and-fix for floor SVGs.

Two modes:

- **Default (keep-all)**: just fix the ids. Walks every traced
  ``<rect class="seat">`` and ``<polygon class="room">``, detects
  the cluster letter / floor prefix, sorts spatially, mints
  sequential valid ids. Auto-grows the slot list to accommodate
  every shape — operators don't lose any traced geometry. The
  caller (CLI verb) then auto-grows ``offices.yaml`` to match the
  new cluster capacity / room list.

- **Prune mode** (``prune=True``): the original aggressive cleanup.
  Drops shapes outside the ``1920x1080`` viewBox, drops near-
  duplicate shapes within ``_DEDUP_PX`` of each other, then
  renumbers per the floor's ``offices.yaml`` cluster spec (drops
  excess). Useful when an Inkscape ``Ctrl+D`` cascade has produced
  many overlapping copies the operator wants flattened.

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

# Detect a cluster letter prefix in an existing seat id, e.g.
# ``5-T-06`` or ``5-T-06-7-2`` (Ctrl+D cascade) → letter ``T``.
_CLUSTER_LETTER_RE = re.compile(r"^\d+-([A-Z])-")
# Detect floor.<NN> in an existing room id (or its ``5.18-1-3``
# Ctrl+D-cascade descendants). Captures the first numeric suffix.
_ROOM_NUM_RE = re.compile(r"^\d+\.(\d+)")

# Register the SVG namespace as the default so writes emit
# <svg xmlns="..."> instead of <ns0:svg xmlns:ns0="...">. Browsers
# reject the prefixed-root form as "not a valid SVG document"
# even though the XML itself is well-formed (xmllint accepts it).
# Sonar will flag the http URI as a low-severity hotspot (S5332);
# this is a W3C namespace identifier, not a fetched URL.
ET.register_namespace("", "http://www.w3.org/2000/svg")


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
    # Post-doctor cluster spec: letter → capacity. The CLI uses this
    # to auto-grow offices.yaml when shapes exceed declared capacity.
    new_clusters: dict[str, int] = field(default_factory=dict)
    # Post-doctor room id list, in spatial order. Ditto auto-grow.
    new_rooms: list[str] = field(default_factory=list)

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
            "new_clusters": dict(self.new_clusters),
            "new_rooms": list(self.new_rooms),
        }


def doctor_svg(
    svg_path: Path,
    floor: Floor,
    *,
    dry_run: bool = False,
    prune: bool = False,
) -> DoctorReport:
    """Fix the ids in ``svg_path`` for ``floor``; optionally prune.

    Default behavior (``prune=False``):

    1. Detect the cluster letter for each seat from its existing id.
       Seats whose ids don't match ``<floor>-<LETTER>-`` are bucketed
       into the first declared cluster letter.
    2. Within each cluster, spatial-sort row-major, mint sequential
       ``<floor>-<LETTER>-<NN>`` ids.
    3. For rooms: detect numeric suffix from existing ``<floor>.<NN>``
       ids; spatial-sort; mint sequential ``<floor>.<NN>`` starting
       at ``min(existing)`` (or ``18`` if no existing valid suffix).
    4. **Keep all traced shapes** — the slot list extends to fit.

    With ``prune=True``:

    1. Drop ``<rect class="seat">`` / ``<polygon class="room">``
       whose center is outside ``1920x1080``.
    2. Drop near-duplicate elements (centers within ``_DEDUP_PX``).
    3. Renumber per the floor's declared cluster spec; drop excess.

    Returns a :class:`DoctorReport`. With ``dry_run=True`` the file
    is not written; the caller can still inspect the report's
    ``new_clusters`` / ``new_rooms`` to preview the effect.
    """
    if not svg_path.is_file():
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"SVG not found: {svg_path}",
            remediation="check the path or create the SVG via Inkscape first",
        )

    tree = _parse(svg_path)
    root = tree.getroot()
    parents = {child: parent for parent in root.iter() for child in parent}

    seats = _select(root, "rect", "seat")
    rooms = _select(root, "polygon", "room")
    seats_before = len(seats)
    rooms_before = len(rooms)

    actions: list[str] = []
    if prune:
        seats_after, rooms_after, new_clusters, new_rooms = _prune_and_renumber(
            seats, rooms, floor, parents, actions
        )
    else:
        seats_after, rooms_after, new_clusters, new_rooms = _keep_all_renumber(
            seats, rooms, floor, actions
        )
    warnings = _capacity_warnings(
        seats_after,
        sum(c.capacity for c in floor.clusters.values()),
        rooms_after,
        len(floor.rooms),
    )

    if not dry_run and actions:
        # Pretty-print before write so floor SVGs in the repo produce a
        # reviewable `git diff` instead of one giant minified line. Issue #54.
        ET.indent(tree, space="  ")
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
        new_clusters=new_clusters,
        new_rooms=new_rooms,
    )


# -- modes ------------------------------------------------------------------


def _prune_and_renumber(
    seats: list[ET.Element],
    rooms: list[ET.Element],
    floor: Floor,
    parents: dict[ET.Element, ET.Element],
    actions: list[str],
) -> tuple[int, int, dict[str, int], list[str]]:
    """Prune mode (existing aggressive behavior). Returns the post-counts."""
    seat_slots = _seat_ids_for(floor.number, floor.clusters)
    room_slots = list(floor.rooms.keys())
    seats, seat_excess = _clean_category(seats, seat_slots, parents, "seats", actions)
    rooms, room_excess = _clean_category(rooms, room_slots, parents, "rooms", actions)
    seats_after = min(len(seats) - seat_excess, len(seat_slots))
    rooms_after = min(len(rooms) - room_excess, len(room_slots))
    # Post-doctor spec is unchanged from the declared one (we dropped to fit).
    new_clusters = {letter: c.capacity for letter, c in floor.clusters.items()}
    new_rooms = list(floor.rooms.keys())
    return seats_after, rooms_after, new_clusters, new_rooms


def _keep_all_renumber(
    seats: list[ET.Element],
    rooms: list[ET.Element],
    floor: Floor,
    actions: list[str],
) -> tuple[int, int, dict[str, int], list[str]]:
    """Keep-all mode: just fix ids; auto-grow slot list to fit every shape."""
    new_clusters = _renumber_seats_keep_all(seats, floor, actions)
    new_rooms = _renumber_rooms_keep_all(rooms, floor, actions)
    return len(seats), len(rooms), new_clusters, new_rooms


def _renumber_seats_keep_all(
    seats: list[ET.Element],
    floor: Floor,
    actions: list[str],
) -> dict[str, int]:
    """Renumber all seats, auto-growing each cluster letter's capacity.

    Returns the post-doctor cluster spec (letter → count).
    """
    default_letter = _default_cluster_letter(floor)
    by_letter: dict[str, list[ET.Element]] = {}
    for el in seats:
        letter = _detect_cluster_letter(el.get("id") or "", default_letter)
        by_letter.setdefault(letter, []).append(el)

    new_caps: dict[str, int] = {}
    renamed_total = 0
    for letter in sorted(by_letter.keys()):
        items = by_letter[letter]
        items.sort(key=_spatial_key)
        for n, el in enumerate(items, start=1):
            new_id = f"{floor.number}-{letter}-{n:02d}"
            if (el.get("id") or "") != new_id:
                el.set("id", new_id)
                renamed_total += 1
        new_caps[letter] = len(items)

    # Preserve declared cluster letters with capacity 0 if no shapes
    # mapped to them (operator may add later — keeps offices.yaml stable).
    for letter in floor.clusters:
        new_caps.setdefault(letter, 0)

    if renamed_total:
        actions.append(f"renamed {renamed_total} seats")
    grown = [
        f"{letter}: {floor.clusters[letter].capacity} -> {cap}"
        for letter, cap in new_caps.items()
        if letter in floor.clusters and cap != floor.clusters[letter].capacity
    ]
    new_letters = sorted(set(new_caps) - set(floor.clusters))
    if new_letters:
        grown.extend(f"+ {letter}: {new_caps[letter]}" for letter in new_letters)
    if grown:
        actions.append(f"clusters: {', '.join(grown)}")
    return new_caps


def _renumber_rooms_keep_all(
    rooms: list[ET.Element],
    floor: Floor,
    actions: list[str],
) -> list[str]:
    """Renumber all rooms, auto-growing the rooms list to fit every shape."""
    if not rooms:
        return list(floor.rooms.keys())
    rooms_sorted = sorted(rooms, key=_spatial_key)
    start = _room_number_start(rooms_sorted, floor)
    new_ids: list[str] = []
    renamed = 0
    for offset, el in enumerate(rooms_sorted):
        new_id = f"{floor.number}.{start + offset}"
        new_ids.append(new_id)
        if (el.get("id") or "") != new_id:
            el.set("id", new_id)
            renamed += 1
    if renamed:
        actions.append(f"renamed {renamed} rooms")
    declared = list(floor.rooms.keys())
    if new_ids != declared:
        added = [r for r in new_ids if r not in floor.rooms]
        if added:
            actions.append(f"+ {len(added)} rooms ({added[0]}..{added[-1]})")
    return new_ids


def _default_cluster_letter(floor: Floor) -> str:
    """First declared cluster letter, or 'T' if none."""
    if floor.clusters:
        return min(floor.clusters.keys())
    return "T"


def _detect_cluster_letter(seat_id: str, default_letter: str) -> str:
    m = _CLUSTER_LETTER_RE.match(seat_id)
    return m.group(1) if m else default_letter


def _room_number_start(rooms_sorted: list[ET.Element], floor: Floor) -> int:
    """Pick the starting NN for room renumbering.

    Uses the smallest valid existing NN (e.g. 18 from ``5.18``) so
    the architect's own first-room number is preserved. Falls back
    to the floor's smallest declared room number, or 18 by default.
    """
    found: list[int] = []
    for el in rooms_sorted:
        m = _ROOM_NUM_RE.match(el.get("id") or "")
        if m:
            found.append(int(m.group(1)))
    if found:
        return min(found)
    declared = [
        int(rid.split(".", 1)[1])
        for rid in floor.rooms
        if "." in rid and rid.split(".", 1)[1].isdigit()
    ]
    if declared:
        return min(declared)
    return 18


# -- prune-mode helpers -----------------------------------------------------


def _parse(svg_path: Path) -> ET.ElementTree:
    """Parse the SVG, wrapping malformed-XML errors as ``OfficeError``."""
    try:
        return ET.parse(svg_path)
    except ET.ParseError as err:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"SVG is not well-formed XML: {svg_path}: {err}",
            remediation="open in Inkscape and re-save as Plain SVG",
        ) from err


def _select(root: ET.Element, tag: str, cls: str) -> list[ET.Element]:
    return [
        el
        for el in root.iter()
        if el.tag == f"{_SVG_NS}{tag}" and (el.get("class") or "").strip() == cls
    ]


def _clean_category(
    items: list[ET.Element],
    slots: list[str],
    parents: dict[ET.Element, ET.Element],
    label: str,
    actions: list[str],
) -> tuple[list[ET.Element], int]:
    """Drop off-page + duplicate items, then renumber. Mutates ``actions``.

    Returns ``(items_after_drops, excess_dropped_during_renumber)``.
    """
    items, off_page = _drop_off_page(items, parents)
    if off_page:
        actions.append(f"dropped {off_page} off-page {label}")
    items, dupes = _dedupe(items, parents)
    if dupes:
        actions.append(f"dropped {dupes} near-duplicate {label}")
    renamed, excess = _assign_ids(items, slots, parents)
    if renamed:
        actions.append(f"renamed {renamed} {label}")
    if excess:
        actions.append(f"dropped {excess} excess {label}")
    return items, excess


def _capacity_warnings(
    seats_after: int, seat_slots: int, rooms_after: int, room_slots: int
) -> list[str]:
    out: list[str] = []
    if seats_after < seat_slots:
        out.append(
            f"{seats_after} seats traced; offices.yaml declares {seat_slots} "
            "(trace more in Inkscape and re-run)"
        )
    if rooms_after < room_slots:
        out.append(
            f"{rooms_after} rooms traced; offices.yaml declares {room_slots} "
            "(trace more in Inkscape and re-run)"
        )
    return out


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
    """Bounding-box center of a ``<rect>`` or ``<polygon>``.

    Polygons with malformed ``points`` (empty, single number, etc.)
    return ``(0.0, 0.0)`` rather than raising — the caller will then
    treat the shape as an off-page outlier and drop it.
    """
    if el.tag == f"{_SVG_NS}rect":
        x = float(el.get("x", 0))
        y = float(el.get("y", 0))
        w = float(el.get("width", 0))
        h = float(el.get("height", 0))
        return (x + w / 2, y + h / 2)
    if el.tag == f"{_SVG_NS}polygon":
        pts = el.get("points", "")
        nums = [float(c) for c in re.split(r"[\s,]+", pts.strip()) if c]
        xs = nums[0::2]
        ys = nums[1::2]
        if not xs or not ys:
            return (0.0, 0.0)
        return ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
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
