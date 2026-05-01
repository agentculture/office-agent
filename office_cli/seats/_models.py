"""Frozen models for assignments and audit entries."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Assignment:
    seat_id: str
    floor: str
    employee_email: str = ""
    last_updated: str = ""
    hidden: bool = False
    notes: str = ""
    effective_from: str = ""
    effective_until: str = ""
    # View-time flag — set by SeatService when role-aware redaction
    # blanked the email/notes. Surface renderers consult this to render
    # "(private)" instead of "(vacant)" for a redacted hidden seat.
    # Never persisted (CSV/Sheets stores write only their FIELDNAMES).
    redacted: bool = False

    @property
    def is_vacant(self) -> bool:
        return not self.employee_email

    def to_dict(self) -> dict[str, object]:
        return {
            "seat_id": self.seat_id,
            "floor": self.floor,
            "employee_email": self.employee_email or None,
            "last_updated": self.last_updated,
            "hidden": self.hidden,
            "notes": self.notes,
            "effective_from": self.effective_from or None,
            "effective_until": self.effective_until or None,
            "redacted": self.redacted,
        }


@dataclass(frozen=True)
class AuditEntry:
    timestamp: str
    actor: str
    action: str
    seat_id: str
    employee_email: str = ""
    old_employee_email: str = ""
    note: str = ""
    extra: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {
            "timestamp": self.timestamp,
            "actor": self.actor,
            "action": self.action,
            "seat_id": self.seat_id,
            "employee_email": self.employee_email or None,
            "old_employee_email": self.old_employee_email or None,
            "note": self.note,
        }
        if self.extra:
            d["extra"] = dict(self.extra)
        return d
