"""``AssignmentStore`` Protocol — the v1/v2 store boundary.

The CSV implementation lives next door; v2 will add a Sheets-backed and a
DynamoDB-backed implementation behind this same Protocol.
"""

from __future__ import annotations

from typing import Iterable, Protocol

from office_cli.seats._models import Assignment


class AssignmentStore(Protocol):
    def list(self) -> list[Assignment]:
        """Return every known assignment row (occupied or vacant)."""

    def get(self, seat_id: str) -> Assignment | None:
        """Return the row for a seat, or ``None`` if absent."""

    def upsert(self, assignment: Assignment) -> None:
        """Insert or replace the row for ``assignment.seat_id``."""

    def upsert_many(self, assignments: Iterable[Assignment]) -> None:
        """Atomic-ish bulk write: persist all rows in one operation."""

    def by_email(self, email: str) -> Assignment | None:
        """Return the (single) assignment for ``email`` or ``None``."""
