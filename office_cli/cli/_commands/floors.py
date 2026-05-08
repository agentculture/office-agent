"""``office floors`` — list and validate floor SVGs against ``offices.yaml``."""

from __future__ import annotations

import argparse
import shutil
from collections import Counter
from pathlib import Path

from office_cli._config import add_data_dir_arg, drive_cache_root, resolve_data_dir
from office_cli.cli._errors import EXIT_USER_ERROR, OfficeError
from office_cli.cli._output import emit_diagnostic, emit_result
from office_cli.floors import Severity, doctor_svg, parse_svg, validate_floor
from office_cli.offices import Floor, load_offices

_HELP_JSON = "Emit structured JSON."
_DOCTOR_HINT_THRESHOLD = 3


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
    floor_index = _index_floors(load_offices(data_dir))
    targets = _resolve_targets(args, floor_index, data_dir)
    payload = [_validate_one(t, floor_index) for t in targets]
    error_count = sum(len(item["errors"]) for item in payload)  # type: ignore[arg-type]
    if args.json:
        emit_result({"results": payload}, json_mode=True)
    else:
        _print_text(payload)
    return EXIT_USER_ERROR if error_count else 0


def cmd_refresh(args: argparse.Namespace) -> int:
    """Bust the Drive hydrator's local cache.

    Removes ``OFFICE_DRIVE_CACHE_DIR`` (default
    ``~/.cache/office-cli/drive``) so the next command that resolves
    via ``OFFICE_DRIVE_ROOT`` re-downloads the Drive tree from
    scratch. Issue #54: replaces the documented `rm -rf` workaround
    operators were running between Drive uploads and validate.
    """
    cache_dir = drive_cache_root()
    existed = cache_dir.exists()
    shutil.rmtree(cache_dir, ignore_errors=True)
    payload = {"cache_dir": str(cache_dir), "removed": existed}
    if args.json:
        emit_result(payload, json_mode=True)
    elif existed:
        emit_result(f"refreshed {cache_dir}", json_mode=False)
    else:
        emit_result(f"nothing to refresh ({cache_dir} did not exist)", json_mode=False)
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Diagnose-and-fix floor SVGs: drop off-page / duplicate shapes,
    renumber per ``offices.yaml`` cluster spec."""
    data_dir = resolve_data_dir(args)
    floor_index = _index_floors(load_offices(data_dir))
    targets = _resolve_targets(args, floor_index, data_dir)
    payload: list[dict[str, object]] = []
    for target in targets:
        floor = floor_index.get(target)
        if floor is None:
            raise OfficeError(
                code=EXIT_USER_ERROR,
                message=f"SVG {target} is not declared in offices.yaml",
                remediation="add a floors entry pointing at this SVG, or pass an SVG that is",
            )
        report = doctor_svg(target, floor, dry_run=bool(args.dry_run))
        payload.append(report.to_dict())
    if args.json:
        emit_result({"results": payload}, json_mode=True)
    else:
        _print_doctor_text(payload)
    return 0


def _print_doctor_text(payload: list[dict[str, object]]) -> None:
    for item in payload:
        prefix = "DRY-RUN" if item["dry_run"] else "OK   "
        emit_result(
            f"{prefix} {item['floor']} ({item['svg']}) "
            f"seats {item['seats_before']}->{item['seats_after']} "
            f"rooms {item['rooms_before']}->{item['rooms_after']}",
            json_mode=False,
        )
        for action in item["actions"]:  # type: ignore[union-attr]
            emit_diagnostic(f"  {action}")
        for warning in item["warnings"]:  # type: ignore[union-attr]
            emit_diagnostic(f"  warn: {warning}")


def _index_floors(offices: dict[str, object]) -> dict[Path, Floor]:
    out: dict[Path, Floor] = {}
    for office in offices.values():
        for floor in office.floors.values():  # type: ignore[attr-defined]
            out[floor.svg.resolve()] = floor
    return out


def _resolve_targets(
    args: argparse.Namespace, floor_index: dict[Path, Floor], data_dir: Path
) -> list[Path]:
    if args.path:
        # First, try the arg as a floor id (`tlv-floor-5`). Operators and
        # agents reach for this form because `office floors list` prints
        # ids, not paths. Issue #51.
        #
        # Floor-id uniqueness is enforced within an office by
        # office_cli/offices/_yaml.py, but NOT globally — two offices
        # could declare the same floor id. Refuse to pick arbitrarily,
        # especially because `doctor` mutates in place.
        id_matches = [path for path, floor in floor_index.items() if floor.id == args.path]
        if len(id_matches) == 1:
            return [id_matches[0]]
        if len(id_matches) > 1:
            joined = ", ".join(str(p) for p in id_matches)
            raise OfficeError(
                code=EXIT_USER_ERROR,
                message=f"floor id {args.path!r} is ambiguous — matches: {joined}",
                remediation="pass an explicit SVG path to disambiguate",
            )
        # Otherwise treat it as a path. Relative paths resolve against the
        # data dir (not cwd) so they line up with floor.svg paths from
        # offices.yaml when --data-dir != $PWD.
        p = Path(args.path)
        return [(p if p.is_absolute() else data_dir / p).resolve()]
    if args.all:
        return sorted(floor_index.keys())
    raise OfficeError(
        code=EXIT_USER_ERROR,
        message="pass a floor id, an SVG path, or --all",
        remediation="example: office floors validate tlv-floor-5",
    )


def _validate_one(target: Path, floor_index: dict[Path, Floor]) -> dict[str, object]:
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
    return {
        "floor": floor.id,
        "svg": str(target),
        "ok": not errors,
        "errors": [i.to_dict() for i in errors],
        "warnings": [i.to_dict() for i in warnings],
        "seat_count": len(svg.seat_ids),
        "room_count": len(svg.room_ids),
        "doctor_hint": _doctor_hint(floor.id, errors),
    }


def _doctor_hint(floor_id: str, errors: list) -> str:
    """Return a non-empty hint when seat-id-format errors look like the
    Inkscape Ctrl+D cascade pattern from issue #54.

    The cascade produces ids like ``5-T-06-7-4-0-8`` — many seat ids
    that share the ``<floor>-<cluster>-`` prefix but fail format. If
    we see ≥3 such errors sharing a prefix, suggest ``office floors
    doctor`` so the operator doesn't have to discover the verb on
    their own.
    """
    prefixes: Counter = Counter()
    for issue in errors:
        if issue.rule != "seat-id-format":
            continue
        prefix = _shared_prefix_of(issue.message)
        if prefix:
            prefixes[prefix] += 1
    if not prefixes:
        return ""
    top, count = prefixes.most_common(1)[0]
    if count < _DOCTOR_HINT_THRESHOLD:
        return ""
    return (
        f"{count} seat ids share prefix {top!r}; this looks like the "
        f"Inkscape Ctrl+D cascade — try: office floors doctor {floor_id}"
    )


def _shared_prefix_of(message: str) -> str:
    """Pull ``<floor>-<cluster>-`` from a ``seat-id-format`` message.

    The validator emits messages like
    ``seat id '5-T-06-7-4' does not match <floor>-<CLUSTER>-<NN>``.
    We extract the id (between the first pair of single quotes) and
    keep up to the second hyphen.
    """
    start = message.find("'")
    end = message.find("'", start + 1) if start >= 0 else -1
    if start < 0 or end <= start:
        return ""
    sid = message[start + 1 : end]
    parts = sid.split("-")
    if len(parts) < 3:
        return ""
    return f"{parts[0]}-{parts[1]}-"


def _print_text(payload: list[dict[str, object]]) -> None:
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
        hint = item.get("doctor_hint")
        if hint:
            emit_diagnostic(f"  hint: {hint}")


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "floors",
        help="List and validate floor SVGs.",
        description="List and validate floor SVGs against data/offices.yaml.",
    )
    inner = p.add_subparsers(dest="floors_cmd")

    p_list = inner.add_parser("list", help="List configured offices and floors.")
    p_list.add_argument("--office", help="Restrict to a single office id.")
    p_list.add_argument("--json", action="store_true", help=_HELP_JSON)
    add_data_dir_arg(p_list)
    p_list.set_defaults(func=cmd_list)

    p_val = inner.add_parser("validate", help="Validate one or all floor SVGs.")
    p_val.add_argument(
        "path",
        nargs="?",
        help="Path to a floor SVG, or a floor id (e.g. 'tlv-floor-5').",
    )
    p_val.add_argument("--all", action="store_true", help="Validate every declared SVG.")
    p_val.add_argument("--json", action="store_true", help=_HELP_JSON)
    add_data_dir_arg(p_val)
    p_val.set_defaults(func=cmd_validate)

    p_doc = inner.add_parser(
        "doctor",
        help="Diagnose and fix floor SVGs (drop off-page/duplicate shapes; renumber).",
        description=(
            "Clean up Inkscape Ctrl+D duplication noise: drop shapes outside the "
            "viewBox, drop near-duplicates, then renumber surviving seats/rooms "
            "per the floor's offices.yaml cluster spec."
        ),
    )
    p_doc.add_argument(
        "path",
        nargs="?",
        help="Path to a floor SVG, or a floor id (e.g. 'tlv-floor-5').",
    )
    p_doc.add_argument("--all", action="store_true", help="Doctor every declared SVG.")
    p_doc.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing the SVG.",
    )
    p_doc.add_argument("--json", action="store_true", help=_HELP_JSON)
    add_data_dir_arg(p_doc)
    p_doc.set_defaults(func=cmd_doctor)

    p_ref = inner.add_parser(
        "refresh",
        help="Bust the local Drive hydrator cache.",
        description=(
            "Remove ~/.cache/office-cli/drive (or $OFFICE_DRIVE_CACHE_DIR) so "
            "the next OFFICE_DRIVE_ROOT-backed command re-downloads the Drive "
            "tree. Use after re-uploading an SVG when iterating with TTL > 0."
        ),
    )
    p_ref.add_argument("--json", action="store_true", help=_HELP_JSON)
    p_ref.set_defaults(func=cmd_refresh)

    p.set_defaults(func=lambda args: _missing_subcommand(p))


def _missing_subcommand(parser: argparse.ArgumentParser) -> int:
    parser.print_help()
    return 0
