"""Append-only audit log for seat changes.

Header::

    timestamp,actor,action,seat_id,employee_email,old_employee_email,note

History is never overwritten; "who used to sit at <seat>?" is just a
chronological filter on this log.

Two implementations live in the codebase:

* :class:`CsvAuditLog` (here) — append-only CSV file, default for v1.
* :class:`office_cli.seats.sheets.SheetsAuditLog` — Sheets-backed.

Both implement the :class:`AuditLog` Protocol, which is what
:class:`office_cli.seats.SeatService` is typed against.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Protocol

from office_cli.seats._models import AuditEntry

FIELDNAMES = [
    "timestamp",
    "actor",
    "action",
    "seat_id",
    "employee_email",
    "old_employee_email",
    "note",
]


class AuditLog(Protocol):
    """Structural type every audit-log backend must satisfy."""

    def append(self, entry: AuditEntry) -> None:
        """Append a single entry."""

    def append_many(self, entries: Iterable[AuditEntry]) -> None:
        """Append multiple entries (atomic-ish per backend)."""

    def all(self) -> list[AuditEntry]:
        """Return every entry in insertion order."""

    def for_seat(self, seat_id: str) -> list[AuditEntry]:
        """Return every entry for ``seat_id``."""


class CsvAuditLog:
    """Append-only CSV implementation of :class:`AuditLog`."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _ensure_file(self) -> None:
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
                writer.writeheader()

    def append(self, entry: AuditEntry) -> None:
        self.append_many([entry])

    def append_many(self, entries: Iterable[AuditEntry]) -> None:
        self._ensure_file()
        with self.path.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            for e in entries:
                writer.writerow(
                    {
                        "timestamp": e.timestamp,
                        "actor": e.actor,
                        "action": e.action,
                        "seat_id": e.seat_id,
                        "employee_email": e.employee_email,
                        "old_employee_email": e.old_employee_email,
                        "note": e.note,
                    }
                )

    def all(self) -> list[AuditEntry]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [
                AuditEntry(
                    timestamp=row.get("timestamp", ""),
                    actor=row.get("actor", ""),
                    action=row.get("action", ""),
                    seat_id=row.get("seat_id", ""),
                    employee_email=row.get("employee_email", ""),
                    old_employee_email=row.get("old_employee_email", ""),
                    note=row.get("note", ""),
                )
                for row in reader
                if row.get("seat_id")
            ]

    def for_seat(self, seat_id: str) -> list[AuditEntry]:
        return [e for e in self.all() if e.seat_id == seat_id]
