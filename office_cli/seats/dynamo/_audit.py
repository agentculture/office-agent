"""DynamoDB-backed append-only audit log.

Schema:

* PK = ``seat_id`` (string).
* SK = ``timestamp`` (ISO-8601 string).

The PK + SK pair gives natural chronological ordering per seat and
makes ``put_item`` idempotent — re-running a batch overwrites the same
keys rather than duplicating rows. ``for_seat`` is a single
``query_by_pk`` instead of a full scan.
"""

from __future__ import annotations

from typing import Iterable

from office_cli.seats._models import AuditEntry
from office_cli.seats.dynamo._client import DynamoClient


class DynamoAuditLog:
    def __init__(self, client: DynamoClient, *, table: str) -> None:
        self._client = client
        self._table = table

    def append(self, entry: AuditEntry) -> None:
        self.append_many([entry])

    def append_many(self, entries: Iterable[AuditEntry]) -> None:
        items = [_entry_to_item(e) for e in entries]
        if not items:
            return
        self._client.batch_put(self._table, items)

    def all(self) -> list[AuditEntry]:
        items = self._client.scan_all(self._table)
        out = [_item_to_entry(it) for it in items if it.get("seat_id")]
        out.sort(key=lambda e: (e.timestamp, e.seat_id))
        return out

    def for_seat(self, seat_id: str) -> list[AuditEntry]:
        items = self._client.query_by_pk(self._table, "seat_id", seat_id)
        out = [_item_to_entry(it) for it in items]
        out.sort(key=lambda e: e.timestamp)
        return out


def _item_to_entry(item: dict) -> AuditEntry:
    return AuditEntry(
        timestamp=str(item.get("timestamp", "")),
        actor=str(item.get("actor", "")),
        action=str(item.get("action", "")),
        seat_id=str(item.get("seat_id", "")),
        employee_email=str(item.get("employee_email", "")),
        old_employee_email=str(item.get("old_employee_email", "")),
        note=str(item.get("note", "")),
    )


def _entry_to_item(e: AuditEntry) -> dict:
    return {
        "seat_id": e.seat_id,
        "timestamp": e.timestamp,
        "actor": e.actor,
        "action": e.action,
        "employee_email": e.employee_email,
        "old_employee_email": e.old_employee_email,
        "note": e.note,
    }
