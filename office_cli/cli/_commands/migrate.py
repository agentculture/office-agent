"""``office seats migrate`` — one-shot import/export between stores.

Any-to-any. Reads from the ``--from`` backend and upserts into the
``--to`` backend. Used to bootstrap Dynamo from Sheets, snapshot
Dynamo back to Sheets for offline review, etc. Audit log is preserved
through the migration.

Idempotency:

* **Assignments**: ``upsert_many`` keys by ``seat_id`` — re-runs are
  safe.
* **Audit**: idempotent when the **target** is Dynamo (PK + SK key
  dedups). Sheets / CSV append-only stores will duplicate audit rows
  on a re-run, so the command bails out early if the target audit log
  is non-empty unless the operator passes ``--audit-append``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from office_cli._config import add_data_dir_arg, resolve_data_dir
from office_cli.cli._errors import EXIT_USER_ERROR, OfficeError
from office_cli.cli._output import emit_diagnostic, emit_result
from office_cli.floors import parse_svg
from office_cli.offices import load_offices
from office_cli.seats import Assignment, build_backends_for_type

_VALID_TYPES = ("csv", "sheets", "dynamo")


def _load_all_svg_seats(data_dir: Path) -> list[tuple[str, str]]:
    """Return ``[(seat_id, floor_id), ...]`` across every floor declared in
    ``data/offices.yaml``. Mirrors the iteration in
    :func:`office_cli.seats.build_service` so migrate can pad its output
    with vacant rows for SVG seats the source store doesn't know about."""
    out: list[tuple[str, str]] = []
    for office in load_offices(data_dir).values():
        for floor_id, floor in office.floors.items():
            if floor.svg.is_file():
                for seat_id in parse_svg(floor.svg).seat_ids:
                    out.append((seat_id, floor_id))
    return out


def cmd_migrate(args: argparse.Namespace) -> int:
    if args.from_type == args.to_type:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"--from and --to are both {args.from_type!r}",
            remediation="pick a different target backend",
        )
    _validate_type("--from", args.from_type)
    _validate_type("--to", args.to_type)

    data_dir = resolve_data_dir(args)
    src_store, src_audit = build_backends_for_type(data_dir, args.from_type)
    tgt_store, tgt_audit = build_backends_for_type(data_dir, args.to_type)

    src_assignments = src_store.list()
    src_audit_entries = src_audit.all()

    # Pad the source list with vacant rows for every SVG seat the source
    # store doesn't already know about. This makes the target backend a
    # complete view of the seat universe — important for Sheets-as-CMS,
    # where HR/facilities need to see vacant seats to assign people. Rows
    # in the source that aren't in any SVG (orphans — someone removed a
    # seat from the SVG without cleaning the store) survive the migration
    # but get reported separately so an operator can act.
    svg_seats = _load_all_svg_seats(data_dir)
    svg_seat_ids = {sid for sid, _ in svg_seats}
    src_seat_ids = {a.seat_id for a in src_assignments}
    padding = [
        Assignment(seat_id=sid, floor=fid) for sid, fid in svg_seats if sid not in src_seat_ids
    ]
    orphans = [a for a in src_assignments if a.seat_id not in svg_seat_ids]
    padded = list(src_assignments) + padding

    tgt_existing = {a.seat_id: a for a in tgt_store.list()}
    new = [a for a in padded if a.seat_id not in tgt_existing]
    overwritten = [a for a in padded if a.seat_id in tgt_existing and tgt_existing[a.seat_id] != a]
    unchanged = len(padded) - len(new) - len(overwritten)

    audit_target_size = len(tgt_audit.all())
    if (
        args.to_type in ("csv", "sheets")
        and audit_target_size
        and not args.audit_append
        and not args.dry_run
    ):
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=(
                f"target audit log is non-empty ({audit_target_size} rows); "
                f"appending would duplicate rows on re-run"
            ),
            remediation=(
                "clear the target audit log first, or pass --audit-append "
                "to accept the duplication"
            ),
        )

    if orphans:
        emit_diagnostic(
            f"orphans: {len(orphans)} row(s) in source not present in any SVG: "
            f"{', '.join(sorted(o.seat_id for o in orphans))}"
        )

    if args.dry_run:
        emit_diagnostic(
            f"DRY RUN: {args.from_type} → {args.to_type}: "
            f"{len(new)} new, {len(overwritten)} overwritten, "
            f"{unchanged} unchanged; {len(orphans)} orphans; "
            f"{len(src_audit_entries)} audit rows"
        )
        if args.json:
            emit_result(
                {
                    "from": args.from_type,
                    "to": args.to_type,
                    "dry_run": True,
                    "assignments_new": len(new),
                    "assignments_overwritten": len(overwritten),
                    "assignments_unchanged": unchanged,
                    "assignments_orphans": len(orphans),
                    "audit_rows": len(src_audit_entries),
                },
                json_mode=True,
            )
        return 0

    tgt_store.upsert_many(padded)
    tgt_audit.append_many(src_audit_entries)

    summary = {
        "from": args.from_type,
        "to": args.to_type,
        "dry_run": False,
        "assignments_written": len(padded),
        "assignments_orphans": len(orphans),
        "audit_rows_written": len(src_audit_entries),
    }
    if args.json:
        emit_result(summary, json_mode=True)
    else:
        emit_result(
            f"migrated {len(padded)} assignments and "
            f"{len(src_audit_entries)} audit rows from "
            f"{args.from_type} to {args.to_type}",
            json_mode=False,
        )
    return 0


def _validate_type(flag: str, value: str) -> None:
    if value not in _VALID_TYPES:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"{flag} must be one of {', '.join(_VALID_TYPES)}; got {value!r}",
            remediation=f"pass {flag} csv | sheets | dynamo",
        )


def register(parent: argparse._SubParsersAction) -> None:
    p = parent.add_parser(
        "migrate",
        help="One-shot import/export between storage backends.",
        description=(
            "Copy assignments and audit-log rows from --from to --to. "
            "Source / target are any of csv, sheets, dynamo (and they "
            "must differ). Idempotent for assignments; audit "
            "idempotency is target-dependent (see --audit-append)."
        ),
    )
    p.add_argument(
        "--from",
        dest="from_type",
        required=True,
        choices=_VALID_TYPES,
        help="Source backend.",
    )
    p.add_argument(
        "--to",
        dest="to_type",
        required=True,
        choices=_VALID_TYPES,
        help="Target backend.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Read source + target, print the diff, write nothing.",
    )
    p.add_argument(
        "--audit-append",
        action="store_true",
        help=(
            "Allow appending audit rows even when the target log is "
            "non-empty (duplicates likely on csv/sheets targets)."
        ),
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    add_data_dir_arg(p)
    p.set_defaults(func=cmd_migrate)
