"""Business logic on top of the store + audit log.

Invariants:

* a seat must exist in some floor's SVG before it can be assigned;
* an employee has at most one seat globally — re-assigning an email that
  already holds a seat is rejected with a hint to use ``move``;
* every mutation appends to the audit log.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from office_cli.cli._errors import EXIT_USER_ERROR, OfficeError
from office_cli.floors import FloorSvg
from office_cli.offices import Office
from office_cli.seats._audit import AuditLog
from office_cli.seats._models import Assignment, AuditEntry
from office_cli.seats._store import AssignmentStore


class SeatService:
    def __init__(
        self,
        offices: dict[str, Office],
        floor_svgs: dict[str, FloorSvg],
        store: AssignmentStore,
        audit: AuditLog,
        actor: str = "cli",
        clock: "callable[[], str] | None" = None,  # type: ignore[name-defined]
    ) -> None:
        self.offices = offices
        self.floor_svgs = floor_svgs
        self.store = store
        self.audit = audit
        self.actor = actor
        self._clock = clock or _utcnow_iso
        self._seat_to_floor = _build_seat_index(offices, floor_svgs)

    # -- Lookups ---------------------------------------------------------

    def list_seats(
        self,
        *,
        floor: str | None = None,
        cluster: str | None = None,
        only_vacant: bool = False,
        only_occupied: bool = False,
    ) -> list[Assignment]:
        existing = {a.seat_id: a for a in self.store.list()}
        out: list[Assignment] = []
        for seat_id, floor_id in sorted(self._seat_to_floor.items()):
            if floor and floor_id != floor:
                continue
            if cluster and not seat_id.split("-")[1:2] == [cluster]:
                continue
            a = existing.get(
                seat_id,
                Assignment(seat_id=seat_id, floor=floor_id),
            )
            if only_vacant and not a.is_vacant:
                continue
            if only_occupied and a.is_vacant:
                continue
            out.append(a)
        return out

    def whereis(self, email: str) -> Assignment | None:
        return self.store.by_email(email)

    def history(self, seat_id: str) -> list[AuditEntry]:
        self._require_seat(seat_id)
        return self.audit.for_seat(seat_id)

    # -- Mutations -------------------------------------------------------

    def assign(
        self,
        seat_id: str,
        email: str,
        *,
        note: str = "",
        hidden: bool = False,
    ) -> Assignment:
        floor_id = self._require_seat(seat_id)
        if not email:
            raise OfficeError(
                code=EXIT_USER_ERROR,
                message="email is required",
                remediation="pass a non-empty email address",
            )
        existing_for_email = self.store.by_email(email)
        if existing_for_email and existing_for_email.seat_id != seat_id:
            raise OfficeError(
                code=EXIT_USER_ERROR,
                message=(
                    f"{email} is already assigned to {existing_for_email.seat_id}; "
                    "an employee can hold at most one seat globally"
                ),
                remediation=f"to move them, run: office seats move {email} {seat_id}",
            )
        current = self.store.get(seat_id)
        old_email = current.employee_email if current else ""
        if current and not current.is_vacant and current.employee_email != email:
            raise OfficeError(
                code=EXIT_USER_ERROR,
                message=f"seat {seat_id} is already assigned to {current.employee_email}",
                remediation=f"unassign first: office seats unassign {seat_id}",
            )
        now = self._clock()
        new = Assignment(
            seat_id=seat_id,
            floor=floor_id,
            employee_email=email,
            last_updated=now,
            hidden=hidden,
            notes=note or (current.notes if current else ""),
            effective_from=now,
            effective_until="",
        )
        self.store.upsert(new)
        self.audit.append(
            AuditEntry(
                timestamp=now,
                actor=self.actor,
                action="assign",
                seat_id=seat_id,
                employee_email=email,
                old_employee_email=old_email,
                note=note,
            )
        )
        return new

    def unassign(self, seat_id: str, *, note: str = "") -> Assignment:
        floor_id = self._require_seat(seat_id)
        current = self.store.get(seat_id)
        if not current or current.is_vacant:
            raise OfficeError(
                code=EXIT_USER_ERROR,
                message=f"seat {seat_id} is already vacant",
                remediation="nothing to do",
            )
        now = self._clock()
        vacated = Assignment(
            seat_id=seat_id,
            floor=floor_id,
            employee_email="",
            last_updated=now,
            hidden=False,
            notes=current.notes,
        )
        self.store.upsert(vacated)
        self.audit.append(
            AuditEntry(
                timestamp=now,
                actor=self.actor,
                action="unassign",
                seat_id=seat_id,
                employee_email="",
                old_employee_email=current.employee_email,
                note=note,
            )
        )
        return vacated

    def move(self, email: str, new_seat_id: str, *, note: str = "") -> Assignment:
        new_floor = self._require_seat(new_seat_id)
        current = self.store.by_email(email)
        if current is None:
            raise OfficeError(
                code=EXIT_USER_ERROR,
                message=f"{email} has no current seat",
                remediation=f"use: office seats assign {new_seat_id} {email}",
            )
        if current.seat_id == new_seat_id:
            return current
        target = self.store.get(new_seat_id)
        if target and not target.is_vacant:
            raise OfficeError(
                code=EXIT_USER_ERROR,
                message=f"seat {new_seat_id} is occupied by {target.employee_email}",
                remediation="unassign or swap; use a different target seat",
            )
        now = self._clock()
        vacated = Assignment(
            seat_id=current.seat_id,
            floor=current.floor,
            employee_email="",
            last_updated=now,
            hidden=False,
            notes=current.notes,
        )
        moved = Assignment(
            seat_id=new_seat_id,
            floor=new_floor,
            employee_email=email,
            last_updated=now,
            hidden=current.hidden,
            notes=note or current.notes,
            effective_from=now,
        )
        self.store.upsert_many([vacated, moved])
        self.audit.append_many(
            [
                AuditEntry(
                    timestamp=now,
                    actor=self.actor,
                    action="unassign",
                    seat_id=current.seat_id,
                    employee_email="",
                    old_employee_email=email,
                    note=f"move → {new_seat_id}",
                ),
                AuditEntry(
                    timestamp=now,
                    actor=self.actor,
                    action="assign",
                    seat_id=new_seat_id,
                    employee_email=email,
                    old_employee_email="",
                    note=note or f"move from {current.seat_id}",
                ),
            ]
        )
        return moved

    # -- Helpers ---------------------------------------------------------

    def _require_seat(self, seat_id: str) -> str:
        floor_id = self._seat_to_floor.get(seat_id)
        if not floor_id:
            raise OfficeError(
                code=EXIT_USER_ERROR,
                message=f"unknown seat: {seat_id}",
                remediation="run: office seats list to see the known seat IDs",
            )
        return floor_id


def _build_seat_index(
    offices: Iterable[Office] | dict[str, Office],
    floor_svgs: dict[str, FloorSvg],
) -> dict[str, str]:
    """Map every seat/room id → floor id by union over loaded SVGs."""
    if isinstance(offices, dict):
        office_iter = offices.values()
    else:
        office_iter = list(offices)
    seat_to_floor: dict[str, str] = {}
    for office in office_iter:
        for floor_id, floor in office.floors.items():
            svg = floor_svgs.get(floor_id)
            if svg is None:
                continue
            for sid in (*svg.seat_ids, *svg.room_ids):
                seat_to_floor.setdefault(sid, floor_id)
            # Rooms declared in YAML even without an SVG entry should still
            # be assignable.
            for rid in floor.rooms:
                seat_to_floor.setdefault(rid, floor_id)
    return seat_to_floor


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
