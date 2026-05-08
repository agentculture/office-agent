"""Floor SVG parsing and validation against ``offices.yaml``."""

from __future__ import annotations

from office_cli.floors._copy_layout import CopyReport, copy_layout
from office_cli.floors._doctor import DoctorReport, doctor_svg
from office_cli.floors._ids import (
    ROOM_RE,
    SEAT_RE,
    is_room_id,
    is_seat_id,
    parse_seat_id,
)
from office_cli.floors._scaffold import scaffold_svg
from office_cli.floors._svg import FloorSvg, parse_svg
from office_cli.floors._validate import Issue, Severity, validate_floor

__all__ = [
    "CopyReport",
    "DoctorReport",
    "FloorSvg",
    "Issue",
    "ROOM_RE",
    "SEAT_RE",
    "Severity",
    "copy_layout",
    "doctor_svg",
    "is_room_id",
    "is_seat_id",
    "parse_seat_id",
    "parse_svg",
    "scaffold_svg",
    "validate_floor",
]
