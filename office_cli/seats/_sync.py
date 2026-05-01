"""Pure last-write-wins reconciliation for the bi-directional ``sync`` verb.

The reconciler operates on two snapshots — a left and a right list of
:class:`Assignment` rows + a left and a right list of :class:`AuditEntry`
rows — and computes the writes needed on each side to bring them into
agreement. No I/O happens here; the CLI driver applies the plan.

Per-row policy is **last-write-wins** by ``last_updated`` ISO-8601
string (lexicographic compare is correct for ISO-8601). Rare ties on
identical ``last_updated`` but diverged content fall back to the
``primary`` argument so the operator picks the tie-breaker.

Audit entries union into both sides, deduped by
``(seat_id, timestamp, action, employee_email)``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from office_cli.seats._models import Assignment, AuditEntry


@dataclass(frozen=True)
class SyncPlan:
    """Result of comparing left and right snapshots.

    ``write_left`` / ``write_right`` are the new or updated assignments
    each side needs. ``audit_left`` / ``audit_right`` are the new audit
    rows each side needs. ``ties`` lists seat IDs where the
    ``last_updated`` matched but content diverged — these were resolved
    via the ``primary`` tie-breaker, but the caller may want to log them.
    """

    write_left: list[Assignment] = field(default_factory=list)
    write_right: list[Assignment] = field(default_factory=list)
    audit_left: list[AuditEntry] = field(default_factory=list)
    audit_right: list[AuditEntry] = field(default_factory=list)
    ties: list[str] = field(default_factory=list)


def reconcile(
    left: Iterable[Assignment],
    right: Iterable[Assignment],
    *,
    primary: str,
    left_audit: Iterable[AuditEntry] = (),
    right_audit: Iterable[AuditEntry] = (),
) -> SyncPlan:
    """Compute a :class:`SyncPlan` for two snapshots.

    ``primary`` must be ``"left"`` or ``"right"`` and is the tie-breaker
    when ``last_updated`` matches but content differs. The CLI maps
    ``--primary sheets`` / ``--primary dynamo`` to left / right.
    """
    if primary not in ("left", "right"):
        raise ValueError(f"primary must be 'left' or 'right'; got {primary!r}")

    left_by_id = {a.seat_id: a for a in left}
    right_by_id = {a.seat_id: a for a in right}
    plan = SyncPlan()

    for seat_id in left_by_id.keys() - right_by_id.keys():
        plan.write_right.append(left_by_id[seat_id])
    for seat_id in right_by_id.keys() - left_by_id.keys():
        plan.write_left.append(right_by_id[seat_id])

    for seat_id in left_by_id.keys() & right_by_id.keys():
        la = left_by_id[seat_id]
        ra = right_by_id[seat_id]
        if _content_eq(la, ra):
            continue  # already aligned
        if la.last_updated > ra.last_updated:
            plan.write_right.append(la)
        elif ra.last_updated > la.last_updated:
            plan.write_left.append(ra)
        else:
            # Same last_updated, diverged content. Pick the primary side.
            plan.ties.append(seat_id)
            if primary == "left":
                plan.write_right.append(la)
            else:
                plan.write_left.append(ra)

    plan.audit_left.extend(_audit_diff(right_audit, left_audit))
    plan.audit_right.extend(_audit_diff(left_audit, right_audit))
    return plan


def _content_eq(a: Assignment, b: Assignment) -> bool:
    """Equal on every persisted column.

    ``redacted`` is a non-persisted view-time flag from Stage 7 — never
    written, so we exclude it from the equality check (the service can
    set it differently on snapshots fetched with different roles).
    """
    return (
        a.seat_id == b.seat_id
        and a.floor == b.floor
        and a.employee_email == b.employee_email
        and a.last_updated == b.last_updated
        and a.hidden == b.hidden
        and a.notes == b.notes
        and a.effective_from == b.effective_from
        and a.effective_until == b.effective_until
    )


def _audit_diff(src: Iterable[AuditEntry], existing: Iterable[AuditEntry]) -> list[AuditEntry]:
    """Return entries from ``src`` whose dedup key isn't in ``existing``."""
    seen = {_audit_key(e) for e in existing}
    out: list[AuditEntry] = []
    for entry in src:
        if _audit_key(entry) not in seen:
            out.append(entry)
            seen.add(_audit_key(entry))
    return out


def _audit_key(e: AuditEntry) -> tuple[str, str, str, str]:
    return (e.seat_id, e.timestamp, e.action, e.employee_email)
