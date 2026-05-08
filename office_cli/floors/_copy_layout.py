"""Copy seats + rooms from one floor SVG into another.

Many floors in a single building share a layout: floor 3 and floor 4
have the same column grid, the same desk arrangement, the same room
boundaries. Re-tracing each one in Inkscape is wasteful when we
already have one clean trace to use as a stencil.

:func:`copy_layout` reads ``src_path``'s ``<rect class="seat">`` and
``<polygon class="room">`` elements verbatim — preserving every
``x/y/width/height`` and ``points`` attribute — appends them into
``dst_path`` (replacing any existing seats/rooms there), then
renumbers the new ids per ``dst_floor.clusters`` and
``dst_floor.rooms``. The dst's embedded ``<image>`` background and
``viewBox`` are preserved unchanged, so the copy lands on top of
dst's own architectural plan.

Reuses the doctor verb's ``_assign_ids`` / ``_select`` /
``_capacity_warnings`` / ``_seat_ids_for`` helpers — same renumbering
contract, just sourcing the elements from another file instead of
the dst's own pre-existing shapes.
"""

from __future__ import annotations

import copy as _copy
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

from office_cli.cli._errors import EXIT_USER_ERROR, OfficeError
from office_cli.floors._doctor import (
    _assign_ids,
    _capacity_warnings,
    _parse,
    _seat_ids_for,
    _select,
)
from office_cli.floors._svg import parse_svg
from office_cli.floors._validate import Severity, validate_floor
from office_cli.offices._models import Floor

# Match doctor + scaffold: emit `<svg xmlns="...">`, not `<ns0:svg ...>`.
ET.register_namespace("", "http://www.w3.org/2000/svg")


@dataclass(frozen=True)
class CopyReport:
    """Outcome of one :func:`copy_layout` invocation."""

    src_floor_id: str
    dst_floor_id: str
    src_path: Path
    dst_path: Path
    seats_copied: int
    rooms_copied: int
    seat_slots: int
    room_slots: int
    actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "src_floor": self.src_floor_id,
            "dst_floor": self.dst_floor_id,
            "src": str(self.src_path),
            "dst": str(self.dst_path),
            "seats_copied": self.seats_copied,
            "rooms_copied": self.rooms_copied,
            "seat_slots": self.seat_slots,
            "room_slots": self.room_slots,
            "actions": list(self.actions),
            "warnings": list(self.warnings),
        }


def copy_layout(
    *,
    src_path: Path,
    src_floor: Floor,
    dst_path: Path,
    dst_floor: Floor,
    overwrite: bool = False,
) -> CopyReport:
    """Stencil src's seats + rooms onto dst, renumbered for dst.

    Refuses to run if:

    - either path is missing on disk;
    - ``src`` has any validation errors (would propagate garbage);
    - ``dst`` is not ``status: draft`` and ``overwrite`` is ``False``
      (defends against clobbering a real trace).
    """
    _ensure_files_exist(src_path, dst_path)
    _ensure_src_clean(src_path, src_floor)
    _ensure_dst_writable(dst_floor, overwrite)

    src_tree = _parse(src_path)
    src_root = src_tree.getroot()
    src_seats = _select(src_root, "rect", "seat")
    src_rooms = _select(src_root, "polygon", "room")

    dst_tree = _parse(dst_path)
    dst_root = dst_tree.getroot()
    seats_parent, rooms_parent = _strip_existing_layout(dst_root)

    new_seats = _clone_into(src_seats, seats_parent or dst_root)
    new_rooms = _clone_into(src_rooms, rooms_parent or dst_root)

    parents = {child: parent for parent in dst_root.iter() for child in parent}
    seat_slots = _seat_ids_for(dst_floor.number, dst_floor.clusters)
    room_slots = list(dst_floor.rooms.keys())
    seat_renamed, seat_excess = _assign_ids(new_seats, seat_slots, parents)
    room_renamed, room_excess = _assign_ids(new_rooms, room_slots, parents)

    actions = _format_actions(
        src_seat_count=len(src_seats),
        src_room_count=len(src_rooms),
        src_floor_id=src_floor.id,
        seat_renamed=seat_renamed,
        seat_excess=seat_excess,
        room_renamed=room_renamed,
        room_excess=room_excess,
    )
    seats_after = min(len(new_seats) - seat_excess, len(seat_slots))
    rooms_after = min(len(new_rooms) - room_excess, len(room_slots))
    warnings = _capacity_warnings(seats_after, len(seat_slots), rooms_after, len(room_slots))

    ET.indent(dst_tree, space="  ")
    dst_tree.write(dst_path, encoding="utf-8", xml_declaration=True)

    return CopyReport(
        src_floor_id=src_floor.id,
        dst_floor_id=dst_floor.id,
        src_path=src_path,
        dst_path=dst_path,
        seats_copied=seats_after,
        rooms_copied=rooms_after,
        seat_slots=len(seat_slots),
        room_slots=len(room_slots),
        actions=actions,
        warnings=warnings,
    )


# -- guards -----------------------------------------------------------------


def _ensure_files_exist(src_path: Path, dst_path: Path) -> None:
    if not src_path.is_file():
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"src SVG not found: {src_path}",
            remediation="check the source floor's svg field in offices.yaml",
        )
    if not dst_path.is_file():
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"dst SVG not found: {dst_path}",
            remediation="run `office floors scaffold <id>` first to create the dst",
        )


def _ensure_src_clean(src_path: Path, src_floor: Floor) -> None:
    src_svg = parse_svg(src_path)
    issues = validate_floor(src_svg, src_floor)
    errors = [i for i in issues if i.severity is Severity.ERROR]
    if errors:
        rules = ", ".join(sorted({i.rule for i in errors}))
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=(
                f"src floor {src_floor.id!r} has {len(errors)} validation "
                f"error(s) ({rules}); refusing to copy a broken layout"
            ),
            remediation="fix the source floor first (try office floors doctor)",
        )


def _ensure_dst_writable(dst_floor: Floor, overwrite: bool) -> None:
    if dst_floor.status != "draft" and not overwrite:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=(
                f"dst floor {dst_floor.id!r} is status: {dst_floor.status!r}; "
                "refusing to clobber a non-draft trace"
            ),
            remediation=(
                "pass --overwrite to copy anyway, or change the dst's "
                "status to draft in offices.yaml"
            ),
        )


# -- tree manipulation ------------------------------------------------------


def _strip_existing_layout(
    root: ET.Element,
) -> tuple[ET.Element | None, ET.Element | None]:
    """Remove every seat/room from the dst root; return their original parents.

    Preserves ``<image>``, layer groups, and anything else (so the
    embedded background and the viewBox stay intact). Returns the
    parent element of the first seat and first room respectively, so
    callers can re-parent the copied shapes into the same Inkscape
    ``<g id="seats">`` / ``<g id="rooms">`` group rather than
    flattening everything to the SVG root. Qodo PR #57.
    """
    parents = {child: parent for parent in root.iter() for child in parent}
    seats = _select(root, "rect", "seat")
    rooms = _select(root, "polygon", "room")
    seats_parent = parents.get(seats[0]) if seats else None
    rooms_parent = parents.get(rooms[0]) if rooms else None
    for el in seats + rooms:
        parent = parents.get(el)
        if parent is not None:
            parent.remove(el)
    return seats_parent, rooms_parent


def _clone_into(elements: list[ET.Element], target: ET.Element) -> list[ET.Element]:
    """Deep-copy ``elements`` into ``target``; return the new copies."""
    out: list[ET.Element] = []
    for el in elements:
        new_el = _copy.deepcopy(el)
        target.append(new_el)
        out.append(new_el)
    return out


def _format_actions(
    *,
    src_seat_count: int,
    src_room_count: int,
    src_floor_id: str,
    seat_renamed: int,
    seat_excess: int,
    room_renamed: int,
    room_excess: int,
) -> list[str]:
    actions = [f"copied {src_seat_count} seats and {src_room_count} rooms from {src_floor_id}"]
    if seat_renamed:
        actions.append(f"renumbered {seat_renamed} seats per dst spec")
    if seat_excess:
        actions.append(f"dropped {seat_excess} excess seats (over capacity)")
    if room_renamed:
        actions.append(f"renumbered {room_renamed} rooms per dst spec")
    if room_excess:
        actions.append(f"dropped {room_excess} excess rooms")
    return actions
