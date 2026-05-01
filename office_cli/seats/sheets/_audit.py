"""Sheets-backed append-only audit log."""

from __future__ import annotations

from typing import Iterable

from office_cli.seats._audit import FIELDNAMES
from office_cli.seats._models import AuditEntry
from office_cli.seats.sheets._client import SheetsClient

_AUDIT_TAB = "audit-log"


class SheetsAuditLog:
    def __init__(self, client: SheetsClient, *, worksheet: str = _AUDIT_TAB) -> None:
        self._client = client
        self._worksheet = worksheet

    def append(self, entry: AuditEntry) -> None:
        self.append_many([entry])

    def append_many(self, entries: Iterable[AuditEntry]) -> None:
        rows = [_entry_to_row(e) for e in entries]
        if not rows:
            return
        existing = self._client.read_rows(self._worksheet)
        if not existing:
            self._client.replace_rows(self._worksheet, [list(FIELDNAMES), *rows])
        else:
            self._client.append_rows(self._worksheet, rows)

    def all(self) -> list[AuditEntry]:
        rows = self._client.read_rows(self._worksheet)
        if not rows:
            return []
        header, *body = rows
        idx = {name: i for i, name in enumerate(header)}
        out: list[AuditEntry] = []
        for row in body:
            if not row or not _cell(row, idx, "seat_id"):
                continue
            out.append(
                AuditEntry(
                    timestamp=_cell(row, idx, "timestamp"),
                    actor=_cell(row, idx, "actor"),
                    action=_cell(row, idx, "action"),
                    seat_id=_cell(row, idx, "seat_id"),
                    employee_email=_cell(row, idx, "employee_email"),
                    old_employee_email=_cell(row, idx, "old_employee_email"),
                    note=_cell(row, idx, "note"),
                )
            )
        return out

    def for_seat(self, seat_id: str) -> list[AuditEntry]:
        return [e for e in self.all() if e.seat_id == seat_id]


def _cell(row: list[str], idx: dict[str, int], name: str) -> str:
    pos = idx.get(name)
    if pos is None or pos >= len(row):
        return ""
    return (row[pos] or "").strip()


def _entry_to_row(e: AuditEntry) -> list[str]:
    values = {
        "timestamp": e.timestamp,
        "actor": e.actor,
        "action": e.action,
        "seat_id": e.seat_id,
        "employee_email": e.employee_email,
        "old_employee_email": e.old_employee_email,
        "note": e.note,
    }
    return [values[name] for name in FIELDNAMES]
