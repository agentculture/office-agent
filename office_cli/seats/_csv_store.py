"""CSV-backed :class:`AssignmentStore`.

File shape (header is required)::

    seat_id,floor,employee_email,last_updated,hidden,notes,effective_from,effective_until

Writes are read-modify-write of the whole file. That is fine for the
hundreds-of-seats scale of v1; the Sheets and DynamoDB stores will
replace this for production.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from office_cli.seats._models import Assignment

FIELDNAMES = [
    "seat_id",
    "floor",
    "employee_email",
    "last_updated",
    "hidden",
    "notes",
    "effective_from",
    "effective_until",
]


class CsvStore:
    """Whole-file read/write CSV store."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _ensure_file(self) -> None:
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
                writer.writeheader()

    def list(self) -> list[Assignment]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [_row_to_assignment(row) for row in reader if row.get("seat_id")]

    def get(self, seat_id: str) -> Assignment | None:
        for a in self.list():
            if a.seat_id == seat_id:
                return a
        return None

    def by_email(self, email: str) -> Assignment | None:
        if not email:
            return None
        for a in self.list():
            if a.employee_email == email:
                return a
        return None

    def upsert(self, assignment: Assignment) -> None:
        self.upsert_many([assignment])

    def upsert_many(self, assignments: Iterable[Assignment]) -> None:
        self._ensure_file()
        existing = {a.seat_id: a for a in self.list()}
        for a in assignments:
            existing[a.seat_id] = a
        ordered = sorted(existing.values(), key=lambda a: (a.floor, a.seat_id))
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
            for a in ordered:
                writer.writerow(_assignment_to_row(a))
        tmp.replace(self.path)


def _row_to_assignment(row: dict[str, str]) -> Assignment:
    return Assignment(
        seat_id=row["seat_id"].strip(),
        floor=row.get("floor", "").strip(),
        employee_email=row.get("employee_email", "").strip(),
        last_updated=row.get("last_updated", "").strip(),
        hidden=str(row.get("hidden", "")).strip().lower() in {"true", "1", "yes"},
        notes=row.get("notes", "").strip(),
        effective_from=row.get("effective_from", "").strip(),
        effective_until=row.get("effective_until", "").strip(),
    )


def _assignment_to_row(a: Assignment) -> dict[str, str]:
    return {
        "seat_id": a.seat_id,
        "floor": a.floor,
        "employee_email": a.employee_email,
        "last_updated": a.last_updated,
        "hidden": "TRUE" if a.hidden else "FALSE",
        "notes": a.notes,
        "effective_from": a.effective_from,
        "effective_until": a.effective_until,
    }
