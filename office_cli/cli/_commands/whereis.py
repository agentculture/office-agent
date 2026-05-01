"""``office whereis EMAIL`` — find a person's seat.

The CLI mirror of the Slack ``/whereis`` slash command; both call the same
:class:`SeatService` underneath.
"""

from __future__ import annotations

import argparse

from office_cli._config import add_data_dir_arg, resolve_data_dir
from office_cli.cli._output import emit_result
from office_cli.seats import build_service


def cmd_whereis(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args)
    service = build_service(data_dir)
    a = service.whereis(args.email)
    if args.json:
        emit_result(
            {"email": args.email, "assignment": a.to_dict() if a else None},
            json_mode=True,
        )
        return 0
    if a is None:
        emit_result(f"{args.email}: no seat", json_mode=False)
        return 0
    emit_result(f"{args.email}: {a.seat_id} ({a.floor})", json_mode=False)
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "whereis",
        help="Look up an employee's seat by email.",
        description="Look up an employee's seat by email.",
    )
    p.add_argument("email")
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    add_data_dir_arg(p)
    p.set_defaults(func=cmd_whereis)
