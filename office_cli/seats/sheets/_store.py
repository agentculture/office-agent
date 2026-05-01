"""Sheets-backed :class:`AssignmentStore`.

Worksheet shape mirrors :mod:`office_cli.seats._csv_store`: header row
followed by one row per assignment. The cache TTL defaults to 5 minutes
per the v1 architecture decision (see ``docs/architecture.md``).
"""

from __future__ import annotations

import time
from typing import Iterable

from office_cli.seats._csv_store import FIELDNAMES
from office_cli.seats._models import Assignment
from office_cli.seats.sheets._client import SheetsClient

_DEFAULT_TTL_SECONDS = 300
_ASSIGNMENTS_TAB = "assignments"


class SheetsStore:
    def __init__(
        self,
        client: SheetsClient,
        *,
        worksheet: str = _ASSIGNMENTS_TAB,
        cache_ttl_seconds: int = _DEFAULT_TTL_SECONDS,
        clock: "callable[[], float] | None" = None,  # type: ignore[name-defined]
    ) -> None:
        self._client = client
        self._worksheet = worksheet
        self._ttl = cache_ttl_seconds
        self._clock = clock or time.monotonic
        self._cache: list[Assignment] | None = None
        self._cache_at: float = 0.0

    # -- AssignmentStore -------------------------------------------------

    def list(self) -> list[Assignment]:
        if self._cache is not None and (self._clock() - self._cache_at) < self._ttl:
            return list(self._cache)
        rows = self._client.read_rows(self._worksheet)
        self._cache = _rows_to_assignments(rows)
        self._cache_at = self._clock()
        return list(self._cache)

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
        existing = {a.seat_id: a for a in self.list()}
        for a in assignments:
            existing[a.seat_id] = a
        ordered = sorted(existing.values(), key=lambda a: (a.floor, a.seat_id))
        rows = [list(FIELDNAMES)] + [_assignment_to_row(a) for a in ordered]
        self._client.replace_rows(self._worksheet, rows)
        self._cache = ordered
        self._cache_at = self._clock()

    # -- Helpers ---------------------------------------------------------

    def invalidate(self) -> None:
        self._cache = None
        self._cache_at = 0.0


def _rows_to_assignments(rows: list[list[str]]) -> list[Assignment]:
    if not rows:
        return []
    header, *body = rows
    idx = {name: i for i, name in enumerate(header)}
    out: list[Assignment] = []
    for row in body:
        if not row or not _cell(row, idx, "seat_id"):
            continue
        out.append(
            Assignment(
                seat_id=_cell(row, idx, "seat_id"),
                floor=_cell(row, idx, "floor"),
                employee_email=_cell(row, idx, "employee_email"),
                last_updated=_cell(row, idx, "last_updated"),
                hidden=_cell(row, idx, "hidden").strip().lower() in {"true", "1", "yes"},
                notes=_cell(row, idx, "notes"),
                effective_from=_cell(row, idx, "effective_from"),
                effective_until=_cell(row, idx, "effective_until"),
            )
        )
    return out


def _cell(row: list[str], idx: dict[str, int], name: str) -> str:
    pos = idx.get(name)
    if pos is None or pos >= len(row):
        return ""
    return (row[pos] or "").strip()


def _assignment_to_row(a: Assignment) -> list[str]:
    values = {
        "seat_id": a.seat_id,
        "floor": a.floor,
        "employee_email": a.employee_email,
        "last_updated": a.last_updated,
        "hidden": "TRUE" if a.hidden else "FALSE",
        "notes": a.notes,
        "effective_from": a.effective_from,
        "effective_until": a.effective_until,
    }
    return [values[name] for name in FIELDNAMES]
