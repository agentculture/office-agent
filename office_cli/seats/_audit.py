"""Append-only CSV audit log for seat changes.

Header::

    timestamp,actor,action,seat_id,employee_email,old_employee_email,note

History is never overwritten; "who used to sit at <seat>?" is just a
chronological filter on this file.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

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


class AuditLog:
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
