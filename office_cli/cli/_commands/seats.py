"""``office seats`` — list, assign, unassign, move, history."""

from __future__ import annotations

import argparse

from office_cli._config import add_data_dir_arg, resolve_data_dir
from office_cli.cli._errors import EXIT_USER_ERROR, OfficeError
from office_cli.cli._output import emit_result
from office_cli.seats import build_service


def cmd_list(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args)
    service = build_service(data_dir)
    if args.vacant and args.occupied:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message="--vacant and --occupied are mutually exclusive",
            remediation="pass at most one of the two",
        )
    rows = service.list_seats(
        floor=args.floor,
        cluster=args.cluster,
        only_vacant=args.vacant,
        only_occupied=args.occupied,
    )
    if args.json:
        emit_result({"seats": [a.to_dict() for a in rows]}, json_mode=True)
        return 0
    if not rows:
        emit_result("no seats match", json_mode=False)
        return 0
    lines = []
    for a in rows:
        who = a.employee_email or "(vacant)"
        marks = "P" if a.hidden else "."
        lines.append(f"{a.seat_id}\t{a.floor}\t{marks}\t{who}\t{a.last_updated}")
    emit_result("\n".join(lines), json_mode=False)
    return 0


def cmd_assign(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args)
    service = build_service(data_dir)
    a = service.assign(args.seat_id, args.email, note=args.note or "", hidden=args.hidden)
    _emit_assignment(a, args.json, "assigned")
    return 0


def cmd_unassign(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args)
    service = build_service(data_dir)
    a = service.unassign(args.seat_id, note=args.note or "")
    _emit_assignment(a, args.json, "unassigned")
    return 0


def cmd_move(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args)
    service = build_service(data_dir)
    a = service.move(args.email, args.new_seat_id, note=args.note or "")
    _emit_assignment(a, args.json, "moved")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args)
    service = build_service(data_dir)
    entries = service.history(args.seat_id)
    if args.json:
        emit_result(
            {"seat_id": args.seat_id, "history": [e.to_dict() for e in entries]},
            json_mode=True,
        )
        return 0
    if not entries:
        emit_result(f"no history for {args.seat_id}", json_mode=False)
        return 0
    lines = []
    for e in entries:
        who = e.employee_email or e.old_employee_email or ""
        lines.append(f"{e.timestamp}\t{e.action}\t{e.seat_id}\t{who}\t{e.note}")
    emit_result("\n".join(lines), json_mode=False)
    return 0


def _emit_assignment(assignment, json_mode: bool, verb: str) -> None:
    if json_mode:
        emit_result({"action": verb, "assignment": assignment.to_dict()}, json_mode=True)
    else:
        who = assignment.employee_email or "(vacant)"
        emit_result(f"{verb}: {assignment.seat_id} → {who}", json_mode=False)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "seats",
        help="List and mutate seat assignments.",
        description="List and mutate seat assignments stored under seats/.",
    )
    inner = p.add_subparsers(dest="seats_cmd")

    p_list = inner.add_parser("list", help="List seats with assignment status.")
    p_list.add_argument("--floor", help="Restrict to a single floor id.")
    p_list.add_argument("--cluster", help="Restrict to a single cluster letter.")
    p_list.add_argument("--vacant", action="store_true", help="Only vacant seats.")
    p_list.add_argument("--occupied", action="store_true", help="Only occupied seats.")
    p_list.add_argument("--json", action="store_true", help="Emit structured JSON.")
    add_data_dir_arg(p_list)
    p_list.set_defaults(func=cmd_list)

    p_assign = inner.add_parser("assign", help="Assign a seat to an employee email.")
    p_assign.add_argument("seat_id")
    p_assign.add_argument("email")
    p_assign.add_argument("--note", help="Optional free-text note.")
    p_assign.add_argument(
        "--hidden", action="store_true", help="Mark assignment as private (hidden=TRUE)."
    )
    p_assign.add_argument("--json", action="store_true")
    add_data_dir_arg(p_assign)
    p_assign.set_defaults(func=cmd_assign)

    p_unassign = inner.add_parser("unassign", help="Vacate a seat.")
    p_unassign.add_argument("seat_id")
    p_unassign.add_argument("--note", help="Optional free-text note.")
    p_unassign.add_argument("--json", action="store_true")
    add_data_dir_arg(p_unassign)
    p_unassign.set_defaults(func=cmd_unassign)

    p_move = inner.add_parser("move", help="Atomically move an employee to a new seat.")
    p_move.add_argument("email")
    p_move.add_argument("new_seat_id")
    p_move.add_argument("--note", help="Optional free-text note.")
    p_move.add_argument("--json", action="store_true")
    add_data_dir_arg(p_move)
    p_move.set_defaults(func=cmd_move)

    p_history = inner.add_parser("history", help="Show audit-log entries for a seat.")
    p_history.add_argument("seat_id")
    p_history.add_argument("--json", action="store_true")
    add_data_dir_arg(p_history)
    p_history.set_defaults(func=cmd_history)

    p.set_defaults(func=lambda args: _missing_subcommand(p))


def _missing_subcommand(parser: argparse.ArgumentParser) -> int:
    parser.print_help()
    return 0
