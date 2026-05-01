"""DynamoDB-backed append-only audit log.

Schema:

* PK = ``seat_id`` (string).
* SK = ``event_id`` — composite key
  ``f"{timestamp}#{action}#{employee_email}"`` so two events for the
  same seat in the same wall-clock second don't collide.

The naked ``timestamp`` is kept as a regular attribute for filtering
and human reading; the SK is the composite ``event_id`` so DynamoDB
sorts chronologically (the timestamp prefix dominates the lex sort)
without losing concurrent events. PK + SK dedups identical writes,
so ``put_item`` is still idempotent for re-runs of ``migrate`` /
``sync`` against the same source.

Why composite-SK rather than nanosecond timestamps: ``SeatService``
generates timestamps at second precision (matches CSV / Sheets
behavior), and bumping precision would split this rule across all
backends. The composite SK keeps the wire shape identical across
stores while making the Dynamo SK collision-free in normal usage.
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
        out.sort(key=lambda e: (e.timestamp, e.seat_id, e.action))
        return out

    def for_seat(self, seat_id: str) -> list[AuditEntry]:
        items = self._client.query_by_pk(self._table, "seat_id", seat_id)
        out = [_item_to_entry(it) for it in items]
        out.sort(key=lambda e: (e.timestamp, e.action))
        return out


def _string(item: dict, key: str) -> str:
    """Coerce a Dynamo attribute to ``str``, mapping ``None`` to empty.

    DynamoDB can return ``None`` for NULL-typed values or partially-
    migrated items. Without this normalization, ``str(None)`` would
    produce the literal string ``"None"`` and leak into CLI output.
    """
    value = item.get(key, "")
    if value is None:
        return ""
    return str(value)


def _item_to_entry(item: dict) -> AuditEntry:
    return AuditEntry(
        timestamp=_string(item, "timestamp"),
        actor=_string(item, "actor"),
        action=_string(item, "action"),
        seat_id=_string(item, "seat_id"),
        employee_email=_string(item, "employee_email"),
        old_employee_email=_string(item, "old_employee_email"),
        note=_string(item, "note"),
    )


def _entry_to_item(e: AuditEntry) -> dict:
    return {
        "seat_id": e.seat_id,
        "event_id": _event_id(e),
        "timestamp": e.timestamp,
        "actor": e.actor,
        "action": e.action,
        "employee_email": e.employee_email,
        "old_employee_email": e.old_employee_email,
        "note": e.note,
    }


def _event_id(e: AuditEntry) -> str:
    """Compose the unique SK so collisions on second-precision timestamps
    don't overwrite earlier audit rows.

    Uses ``#`` as the separator since it sorts before any alphanumeric
    character — the timestamp prefix still dominates the lex order, so
    chronological queries return events in wall-clock order.
    """
    return f"{e.timestamp}#{e.action}#{e.employee_email}"
