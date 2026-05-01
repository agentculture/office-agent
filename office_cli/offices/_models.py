"""Frozen dataclasses for the office topology."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Cluster:
    letter: str
    capacity: int
    type: str = "open-space"


@dataclass(frozen=True)
class Room:
    id: str
    name: str
    type: str = "meeting"
    capacity: int = 0


@dataclass(frozen=True)
class Floor:
    id: str
    svg: Path
    clusters: dict[str, Cluster] = field(default_factory=dict)
    rooms: dict[str, Room] = field(default_factory=dict)
    status: str = "active"

    @property
    def number(self) -> str:
        """Floor number segment used in seat IDs (e.g. ``5`` from ``tlv-floor-5``)."""
        last = self.id.rsplit("-", 1)[-1]
        return last


@dataclass(frozen=True)
class Office:
    id: str
    name: str
    address: str = ""
    floors: dict[str, Floor] = field(default_factory=dict)
