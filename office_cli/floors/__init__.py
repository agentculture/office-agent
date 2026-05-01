"""Floor SVG parsing and validation against ``offices.yaml``."""

from __future__ import annotations

from office_cli.floors._ids import (
    ROOM_RE,
    SEAT_RE,
    is_room_id,
    is_seat_id,
    parse_seat_id,
)
from office_cli.floors._svg import FloorSvg, parse_svg
from office_cli.floors._validate import Issue, Severity, validate_floor

__all__ = [
    "FloorSvg",
    "Issue",
    "ROOM_RE",
    "SEAT_RE",
    "Severity",
    "is_room_id",
    "is_seat_id",
    "parse_seat_id",
    "parse_svg",
    "validate_floor",
]
