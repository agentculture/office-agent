"""DynamoDB-backed :class:`AssignmentStore`.

Item shape mirrors :mod:`office_cli.seats._csv_store` columns:

* PK ``seat_id`` (string).
* String attrs: ``floor``, ``employee_email``, ``last_updated``,
  ``notes``, ``effective_from``, ``effective_until``.
* Boolean attr: ``hidden``.

The 5-minute TTL cache mirrors :class:`SheetsStore` so the read path
behavior is identical: one ``scan`` populates the cache, ``by_email``
filters in memory. A GSI on ``employee_email`` is documented as a
Stage-9 hardening; for v1's hundreds-of-seats scale the cache + scan
is fine and keeps the Protocol behavior aligned across backends.
"""

from __future__ import annotations

import time
from typing import Iterable

from office_cli.seats._models import Assignment
from office_cli.seats.dynamo._client import DynamoClient

_DEFAULT_TTL_SECONDS = 300


class DynamoStore:
    def __init__(
        self,
        client: DynamoClient,
        *,
        table: str,
        cache_ttl_seconds: int = _DEFAULT_TTL_SECONDS,
        clock: "callable[[], float] | None" = None,  # type: ignore[name-defined]
    ) -> None:
        self._client = client
        self._table = table
        self._ttl = cache_ttl_seconds
        self._clock = clock or time.monotonic
        self._cache: list[Assignment] | None = None
        self._cache_at: float = 0.0

    # -- AssignmentStore -------------------------------------------------

    def list(self) -> list[Assignment]:
        if self._cache is not None and (self._clock() - self._cache_at) < self._ttl:
            return list(self._cache)
        items = self._client.scan_all(self._table)
        self._cache = [_item_to_assignment(it) for it in items if it.get("seat_id")]
        self._cache.sort(key=lambda a: (a.floor, a.seat_id))
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
        self._client.put_item(self._table, _assignment_to_item(assignment))
        self.invalidate()

    def upsert_many(self, assignments: Iterable[Assignment]) -> None:
        items = [_assignment_to_item(a) for a in assignments]
        if not items:
            return
        self._client.batch_put(self._table, items)
        self.invalidate()

    # -- Helpers ---------------------------------------------------------

    def invalidate(self) -> None:
        self._cache = None
        self._cache_at = 0.0


def _item_to_assignment(item: dict) -> Assignment:
    return Assignment(
        seat_id=str(item.get("seat_id", "")),
        floor=str(item.get("floor", "")),
        employee_email=str(item.get("employee_email", "")),
        last_updated=str(item.get("last_updated", "")),
        hidden=bool(item.get("hidden", False)),
        notes=str(item.get("notes", "")),
        effective_from=str(item.get("effective_from", "")),
        effective_until=str(item.get("effective_until", "")),
    )


def _assignment_to_item(a: Assignment) -> dict:
    return {
        "seat_id": a.seat_id,
        "floor": a.floor,
        "employee_email": a.employee_email,
        "last_updated": a.last_updated,
        "hidden": bool(a.hidden),
        "notes": a.notes,
        "effective_from": a.effective_from,
        "effective_until": a.effective_until,
    }
