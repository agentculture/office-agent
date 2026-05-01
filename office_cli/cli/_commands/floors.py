"""``office floors`` — list and validate floor SVGs against ``offices.yaml``."""

from __future__ import annotations

import argparse
from pathlib import Path

from office_cli._config import add_data_dir_arg, resolve_data_dir
from office_cli.cli._errors import EXIT_USER_ERROR, OfficeError
from office_cli.cli._output import emit_diagnostic, emit_result
from office_cli.floors import Severity, parse_svg, validate_floor
from office_cli.offices import Floor, load_offices


def cmd_list(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args)
    offices = load_offices(data_dir)
    json_mode = bool(args.json)
    if args.office and args.office not in offices:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"unknown office: {args.office}",
            remediation="run: office floors list to see known offices",
        )
    items: list[dict[str, object]] = []
    for office in offices.values():
        if args.office and office.id != args.office:
            continue
        for floor in office.floors.values():
            items.append(
                {
                    "office": office.id,
                    "floor": floor.id,
                    "status": floor.status,
                    "svg": str(floor.svg),
                    "clusters": {letter: c.capacity for letter, c in floor.clusters.items()},
                    "rooms": list(floor.rooms.keys()),
                }
            )
    if json_mode:
        emit_result({"floors": items}, json_mode=True)
        return 0
    if not items:
        emit_result("no floors", json_mode=False)
        return 0
    lines = []
    for it in items:
        clusters = ", ".join(
            f"{k}={v}" for k, v in sorted(it["clusters"].items())  # type: ignore[arg-type]
        )
        lines.append(
            f"{it['office']}\t{it['floor']}\t{it['status']}\t"
            f"clusters[{clusters}]\trooms={len(it['rooms'])}"  # type: ignore[arg-type]
        )
    emit_result("\n".join(lines), json_mode=False)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args)
    offices = load_offices(data_dir)
    floor_index: dict[Path, Floor] = {}
    for office in offices.values():
        for floor in office.floors.values():
            floor_index[floor.svg.resolve()] = floor

    targets: list[Path]
    if args.path:
        targets = [Path(args.path).resolve()]
    elif args.all:
        targets = sorted(floor_index.keys())
    else:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message="pass an SVG path or --all",
            remediation="example: office floors validate floors/tlv-floor-5.svg",
        )

    payload: list[dict[str, object]] = []
    error_count = 0
    for target in targets:
        floor = floor_index.get(target)
        if floor is None:
            raise OfficeError(
                code=EXIT_USER_ERROR,
                message=f"SVG {target} is not declared in offices.yaml",
                remediation="add a floors entry pointing at this SVG",
            )
        svg = parse_svg(target)
        issues = validate_floor(svg, floor)
        errors = [i for i in issues if i.severity is Severity.ERROR]
        warnings = [i for i in issues if i.severity is Severity.WARNING]
        error_count += len(errors)
        payload.append(
            {
                "floor": floor.id,
                "svg": str(target),
                "ok": not errors,
                "errors": [i.to_dict() for i in errors],
                "warnings": [i.to_dict() for i in warnings],
                "seat_count": len(svg.seat_ids),
                "room_count": len(svg.room_ids),
            }
        )

    if args.json:
        emit_result({"results": payload}, json_mode=True)
    else:
        for item in payload:
            mark = "OK " if item["ok"] else "FAIL"
            emit_result(
                f"{mark} {item['floor']} ({item['svg']}) "
                f"seats={item['seat_count']} rooms={item['room_count']}",
                json_mode=False,
            )
            for err in item["errors"]:  # type: ignore[union-attr]
                emit_diagnostic(f"  error [{err['rule']}]: {err['message']}")
            for warn in item["warnings"]:  # type: ignore[union-attr]
                emit_diagnostic(f"  warn  [{warn['rule']}]: {warn['message']}")
    return EXIT_USER_ERROR if error_count else 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "floors",
        help="List and validate floor SVGs.",
        description="List and validate floor SVGs against data/offices.yaml.",
    )
    inner = p.add_subparsers(dest="floors_cmd")

    p_list = inner.add_parser("list", help="List configured offices and floors.")
    p_list.add_argument("--office", help="Restrict to a single office id.")
    p_list.add_argument("--json", action="store_true", help="Emit structured JSON.")
    add_data_dir_arg(p_list)
    p_list.set_defaults(func=cmd_list)

    p_val = inner.add_parser("validate", help="Validate one or all floor SVGs.")
    p_val.add_argument("path", nargs="?", help="Path to a floor SVG.")
    p_val.add_argument("--all", action="store_true", help="Validate every declared SVG.")
    p_val.add_argument("--json", action="store_true", help="Emit structured JSON.")
    add_data_dir_arg(p_val)
    p_val.set_defaults(func=cmd_validate)

    p.set_defaults(func=lambda args: _missing_subcommand(p))


def _missing_subcommand(parser: argparse.ArgumentParser) -> int:
    parser.print_help()
    return 0
