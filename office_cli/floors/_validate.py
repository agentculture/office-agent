"""Validate a parsed :class:`FloorSvg` against an ``offices.yaml`` floor entry."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum

from office_cli.floors._ids import is_room_id, is_seat_id, parse_seat_id
from office_cli.floors._svg import FloorSvg
from office_cli.offices._models import Floor

_EXPECTED_VIEW_BOX = "0 0 1920 1080"


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Issue:
    severity: Severity
    rule: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity.value,
            "rule": self.rule,
            "message": self.message,
        }


def validate_floor(svg: FloorSvg, floor: Floor) -> list[Issue]:
    """Return a list of issues; empty list means the SVG conforms."""
    issues: list[Issue] = []
    issues.extend(_check_view_box(svg))
    issues.extend(_check_duplicates(svg))
    for sid in svg.seat_ids:
        issues.extend(_check_seat(sid, floor))
    for rid in svg.room_ids:
        issues.extend(_check_room(rid, floor))
    issues.extend(_check_untagged(svg))
    issues.extend(_check_capacity(svg, floor))
    return issues


def _check_view_box(svg: FloorSvg) -> list[Issue]:
    if svg.view_box == _EXPECTED_VIEW_BOX:
        return []
    return [
        Issue(
            Severity.ERROR,
            "view-box",
            f"viewBox is {svg.view_box!r}; expected {_EXPECTED_VIEW_BOX!r}",
        )
    ]


def _check_duplicates(svg: FloorSvg) -> list[Issue]:
    return [
        Issue(Severity.ERROR, "duplicate-id", f"id {sid!r} appears more than once")
        for sid in svg.duplicate_ids
    ]


def _check_seat(sid: str, floor: Floor) -> list[Issue]:
    if not is_seat_id(sid):
        return [
            Issue(
                Severity.ERROR,
                "seat-id-format",
                f"seat id {sid!r} does not match <floor>-<CLUSTER>-<NN>",
            )
        ]
    parsed = parse_seat_id(sid)
    out: list[Issue] = []
    if parsed.floor != floor.number:
        out.append(
            Issue(
                Severity.ERROR,
                "seat-floor-mismatch",
                f"seat {sid!r} starts with floor {parsed.floor!r}; "
                f"expected {floor.number!r} (from floor id {floor.id!r})",
            )
        )
    if parsed.cluster not in floor.clusters:
        out.append(
            Issue(
                Severity.ERROR,
                "unknown-cluster",
                f"seat {sid!r} references cluster {parsed.cluster!r} "
                f"not declared for floor {floor.id!r}",
            )
        )
    return out


def _check_room(rid: str, floor: Floor) -> list[Issue]:
    if not is_room_id(rid):
        return [
            Issue(
                Severity.ERROR,
                "room-id-format",
                f"room id {rid!r} does not match the architect <N>.<NN> pattern",
            )
        ]
    if rid not in floor.rooms:
        return [
            Issue(
                Severity.WARNING,
                "room-not-in-yaml",
                f"room {rid!r} present in SVG but not declared in offices.yaml "
                f"for floor {floor.id!r}",
            )
        ]
    return []


def _check_untagged(svg: FloorSvg) -> list[Issue]:
    return [
        Issue(
            Severity.ERROR,
            "missing-class",
            f'id {sid!r} looks like a seat/room but has no class="seat"/"room"',
        )
        for sid in svg.untagged_ids
        if is_seat_id(sid) or is_room_id(sid)
    ]


def _check_capacity(svg: FloorSvg, floor: Floor) -> list[Issue]:
    counts = Counter(parse_seat_id(s).cluster for s in svg.seat_ids if is_seat_id(s))
    return [
        Issue(
            Severity.WARNING,
            "cluster-capacity-mismatch",
            f"cluster {letter!r} has {counts.get(letter, 0)} seats in SVG; "
            f"offices.yaml declares capacity {cluster.capacity}",
        )
        for letter, cluster in floor.clusters.items()
        if counts.get(letter, 0) != cluster.capacity
    ]
