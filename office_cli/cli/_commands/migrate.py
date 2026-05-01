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

from office_cli._config import add_data_dir_arg, resolve_data_dir
from office_cli.cli._errors import EXIT_USER_ERROR, OfficeError
from office_cli.cli._output import emit_diagnostic, emit_result
from office_cli.seats import build_backends_for_type

_VALID_TYPES = ("csv", "sheets", "dynamo")


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

    tgt_existing = {a.seat_id: a for a in tgt_store.list()}
    new = [a for a in src_assignments if a.seat_id not in tgt_existing]
    overwritten = [
        a for a in src_assignments if a.seat_id in tgt_existing and tgt_existing[a.seat_id] != a
    ]
    unchanged = len(src_assignments) - len(new) - len(overwritten)

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

    if args.dry_run:
        emit_diagnostic(
            f"DRY RUN: {args.from_type} → {args.to_type}: "
            f"{len(new)} new, {len(overwritten)} overwritten, "
            f"{unchanged} unchanged; {len(src_audit_entries)} audit rows"
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
                    "audit_rows": len(src_audit_entries),
                },
                json_mode=True,
            )
        return 0

    tgt_store.upsert_many(src_assignments)
    tgt_audit.append_many(src_audit_entries)

    summary = {
        "from": args.from_type,
        "to": args.to_type,
        "dry_run": False,
        "assignments_written": len(src_assignments),
        "audit_rows_written": len(src_audit_entries),
    }
    if args.json:
        emit_result(summary, json_mode=True)
    else:
        emit_result(
            f"migrated {len(src_assignments)} assignments and "
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
