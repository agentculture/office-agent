"""``office seats sync`` — bi-directional reconciliation between Sheets and Dynamo.

Operator workflow: Sheets is the human-friendly editor; Dynamo is the
runtime read path. ``office seats sync`` keeps them in agreement via
last-write-wins on ``last_updated``. Run periodically (cron / GitHub
Action). The ``--primary`` flag picks the tie-breaker when both sides
have an identical ``last_updated`` but diverged content (rare).

Idempotency: re-running converges. The reconciler computes the
minimal set of writes per side; once both sides agree the plan is
empty and the verb is a no-op.
"""

from __future__ import annotations

import argparse

from office_cli._config import add_data_dir_arg, resolve_data_dir
from office_cli.cli._errors import EXIT_USER_ERROR, OfficeError
from office_cli.cli._output import emit_diagnostic, emit_result
from office_cli.seats import build_backends_for_type
from office_cli.seats._sync import reconcile

_PRIMARY_TO_TYPE = {"sheets": "sheets", "dynamo": "dynamo"}


def cmd_sync(args: argparse.Namespace) -> int:
    primary = args.primary
    if primary not in _PRIMARY_TO_TYPE:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"--primary must be 'sheets' or 'dynamo'; got {primary!r}",
            remediation="pass --primary sheets | dynamo",
        )

    data_dir = resolve_data_dir(args)
    sheets_store, sheets_audit = build_backends_for_type(data_dir, "sheets")
    dynamo_store, dynamo_audit = build_backends_for_type(data_dir, "dynamo")

    sheets_rows = sheets_store.list()
    dynamo_rows = dynamo_store.list()
    sheets_audit_rows = sheets_audit.all()
    dynamo_audit_rows = dynamo_audit.all()

    # Map "sheets" / "dynamo" to "left" / "right" so the reconciler
    # stays surface-neutral. Sheets is the left side by convention.
    plan = reconcile(
        left=sheets_rows,
        right=dynamo_rows,
        left_audit=sheets_audit_rows,
        right_audit=dynamo_audit_rows,
        primary="left" if primary == "sheets" else "right",
    )

    summary = {
        "primary": primary,
        "dry_run": args.dry_run,
        "sheets_writes": len(plan.write_left),
        "dynamo_writes": len(plan.write_right),
        "sheets_audit_appends": len(plan.audit_left),
        "dynamo_audit_appends": len(plan.audit_right),
        "ties": list(plan.ties),
    }

    if plan.ties:
        emit_diagnostic(
            f"sync: {len(plan.ties)} content tie(s) on {primary} side: " f"{', '.join(plan.ties)}"
        )

    if args.dry_run:
        emit_diagnostic(
            f"DRY RUN: sheets ← {len(plan.write_left)} rows, "
            f"dynamo ← {len(plan.write_right)} rows; "
            f"audit appends sheets={len(plan.audit_left)}, "
            f"dynamo={len(plan.audit_right)}"
        )
        if args.json:
            emit_result(summary, json_mode=True)
        return 0

    if plan.write_left:
        sheets_store.upsert_many(plan.write_left)
    if plan.write_right:
        dynamo_store.upsert_many(plan.write_right)
    if plan.audit_left:
        sheets_audit.append_many(plan.audit_left)
    if plan.audit_right:
        dynamo_audit.append_many(plan.audit_right)

    if args.json:
        emit_result(summary, json_mode=True)
    else:
        emit_result(
            f"synced: sheets ← {len(plan.write_left)}, "
            f"dynamo ← {len(plan.write_right)}; "
            f"audit appends sheets={len(plan.audit_left)}, "
            f"dynamo={len(plan.audit_right)}",
            json_mode=False,
        )
    return 0


def register(parent: argparse._SubParsersAction) -> None:
    p = parent.add_parser(
        "sync",
        help="Bi-directional reconciliation between Sheets and Dynamo.",
        description=(
            "Reconcile assignments and audit-log rows between the Sheets "
            "and Dynamo backends with last-write-wins per row by "
            "`last_updated`. Run periodically to keep the spreadsheet UI "
            "and the Dynamo runtime in agreement. Idempotent."
        ),
    )
    p.add_argument(
        "--primary",
        required=True,
        choices=("sheets", "dynamo"),
        help=("Tie-breaker when last_updated matches on both sides " "but content diverged."),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the reconciliation plan, write nothing.",
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    add_data_dir_arg(p)
    p.set_defaults(func=cmd_sync)
