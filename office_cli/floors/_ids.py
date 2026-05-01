"""Canonical ID contract for floor SVGs.

Mirrors the SVG ID rules in
``CLAUDE.md`` and `agentculture/office-agent#1
<https://github.com/agentculture/office-agent/issues/1>`_.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SEAT_RE = re.compile(r"^(?P<floor>\d+)-(?P<cluster>[A-Z])-(?P<num>\d{2})$")
ROOM_RE = re.compile(r"^\d+\.\d+$")
CLUSTER_BOUNDARY_RE = re.compile(r"^cluster-\d+-[A-Z]$")


@dataclass(frozen=True)
class SeatId:
    floor: str
    cluster: str
    num: int

    def __str__(self) -> str:
        return f"{self.floor}-{self.cluster}-{self.num:02d}"


def is_seat_id(s: str) -> bool:
    return SEAT_RE.match(s) is not None


def is_room_id(s: str) -> bool:
    return ROOM_RE.match(s) is not None


def parse_seat_id(s: str) -> SeatId:
    m = SEAT_RE.match(s)
    if not m:
        raise ValueError(f"not a seat id: {s!r}")
    return SeatId(floor=m["floor"], cluster=m["cluster"], num=int(m["num"]))
