"""``office floors`` — list and validate floor SVGs against ``offices.yaml``."""

from __future__ import annotations

import argparse
import shutil
from collections import Counter
from pathlib import Path

from office_cli._config import add_data_dir_arg, drive_cache_root, resolve_data_dir
from office_cli.cli._errors import EXIT_USER_ERROR, OfficeError
from office_cli.cli._output import emit_diagnostic, emit_result
from office_cli.floors import Severity, doctor_svg, parse_svg, scaffold_svg, validate_floor
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

    Defends against a footgun: a typo in ``OFFICE_DRIVE_CACHE_DIR``
    (e.g. ``/``) would otherwise let this verb wipe arbitrary trees.
    The resolved path must contain ``office-cli`` as a literal
    component, or the verb refuses with ``EXIT_USER_ERROR``.
    """
    cache_dir = drive_cache_root().resolve()
    _ensure_safe_cache_path(cache_dir)
    if not cache_dir.exists():
        payload = {"cache_dir": str(cache_dir), "removed": False}
        if args.json:
            emit_result(payload, json_mode=True)
        else:
            emit_result(
                f"nothing to refresh ({cache_dir} did not exist)",
                json_mode=False,
            )
        return 0
    try:
        if cache_dir.is_dir() and not cache_dir.is_symlink():
            shutil.rmtree(cache_dir)
        else:
            cache_dir.unlink()
    except OSError as err:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"failed to remove Drive cache at {cache_dir}: {err}",
            remediation=(
                "check filesystem permissions on the cache dir, or remove it "
                "manually with `rm -rf <path>` once the underlying issue is fixed"
            ),
        ) from err
    if cache_dir.exists():
        # rmtree returned without raising but something is still there
        # (e.g. a concurrent process recreated the dir). Surface this
        # so operators don't silently keep serving stale Drive data.
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"Drive cache at {cache_dir} still exists after refresh",
            remediation="check for a concurrent process holding the cache; remove it manually",
        )
    payload = {"cache_dir": str(cache_dir), "removed": True}
    if args.json:
        emit_result(payload, json_mode=True)
    else:
        emit_result(f"refreshed {cache_dir}", json_mode=False)
    return 0


def _ensure_safe_cache_path(cache_dir: Path) -> None:
    """Refuse to delete obviously-dangerous targets.

    The cache dir must contain ``office-cli`` as a literal path
    component. The default (``~/.cache/office-cli/drive``) and any
    sensible ``OFFICE_DRIVE_CACHE_DIR`` override (e.g.
    ``/tmp/test-office-cli/drive``) satisfy this — but ``/``,
    ``$HOME``, ``~/.cache``, etc. do not.
    """
    if "office-cli" not in cache_dir.parts:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=(
                f"refusing to delete {cache_dir}: path must contain 'office-cli' " "as a component"
            ),
            remediation=(
                "unset OFFICE_DRIVE_CACHE_DIR (use the default "
                "~/.cache/office-cli/drive) or set it to a path under an "
                "office-cli-named directory"
            ),
        )


def cmd_scaffold(args: argparse.Namespace) -> int:
    """Generate a placeholder SVG (embedded PDF page + 1 example seat +
    1 example room) for a declared floor. Issue #54.

    Two modes:

    - **Single**: ``office floors scaffold <floor-id> --pdf <p> --page <N>``.
    - **Manifest**: ``office floors scaffold --manifest <yaml>``. The
      manifest declares ``pdf:`` (one path used for all entries) and a
      list of ``{id, page}`` pairs.

    Refuses to overwrite an existing SVG without ``--force``.
    """
    data_dir = resolve_data_dir(args)
    floor_index = _index_floors(load_offices(data_dir))
    jobs = _scaffold_jobs(args, data_dir)

    # Phase 1 — resolve every job (id → floor + out path; check overwrite).
    # Manifests must be all-or-nothing: a bad job at index 5 must not leave
    # files written by jobs 1-4. Qodo PR #56.
    plan: list[tuple[str, Path, int | str, Floor, Path]] = []
    for floor_id, pdf_path, page in jobs:
        floor, existing_path = _resolve_scaffold_floor(floor_id, floor_index)
        out_path = _scaffold_out_path(args, existing_path, data_dir)
        if out_path.exists() and not args.force:
            raise OfficeError(
                code=EXIT_USER_ERROR,
                message=f"refusing to overwrite existing SVG: {out_path}",
                remediation="pass --force to overwrite, or remove the file first",
            )
        plan.append((floor_id, pdf_path, page, floor, out_path))

    # Phase 2 — render every SVG into memory. Any poppler error here also
    # leaves the filesystem untouched.
    rendered: list[tuple[str, Path, int | str, Path, bytes]] = []
    for floor_id, pdf_path, page, floor, out_path in plan:
        svg_bytes = scaffold_svg(floor=floor, pdf=pdf_path, page=page)
        rendered.append((floor_id, pdf_path, page, out_path, svg_bytes))

    # Phase 3 — write everything. If write fails midway it's a filesystem
    # problem the operator needs to know about; we don't try to roll back
    # already-written files (would mask the underlying issue).
    payload: list[dict[str, object]] = []
    for floor_id, pdf_path, page, out_path, svg_bytes in rendered:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(svg_bytes)
        payload.append(
            {
                "floor": floor_id,
                "svg": str(out_path),
                "pdf": str(pdf_path),
                "page": page,
                "bytes": len(svg_bytes),
            }
        )
    if args.json:
        emit_result({"results": payload}, json_mode=True)
    else:
        for item in payload:
            emit_result(
                f"OK   {item['floor']} ({item['svg']}) "
                f"<- {item['pdf']} page {item['page']} "
                f"[{item['bytes']} bytes]",
                json_mode=False,
            )
    return 0


def _scaffold_jobs(args: argparse.Namespace, data_dir: Path) -> list[tuple[str, Path, int | str]]:
    """Resolve `--manifest` or single-floor flags into a job list."""
    if args.manifest:
        return _scaffold_jobs_from_manifest(Path(args.manifest).expanduser(), data_dir)
    if not args.floor_id:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message="pass a floor id or --manifest <yaml>",
            remediation="example: office floors scaffold tlv-floor-3 --pdf <pdf> --page 8",
        )
    if not args.pdf:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message="--pdf is required in single-floor mode",
            remediation="pass --pdf <path-to-architects.pdf>",
        )
    if not args.page:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message="--page is required in single-floor mode",
            remediation="pass --page <N> (1-based) or --page <label>",
        )
    return [(args.floor_id, Path(args.pdf).expanduser(), _coerce_page(args.page))]


def _scaffold_jobs_from_manifest(
    manifest_path: Path, data_dir: Path
) -> list[tuple[str, Path, int | str]]:
    """Parse the manifest YAML; raise on shape errors."""
    import yaml

    if not manifest_path.is_file():
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"manifest not found: {manifest_path}",
            remediation="check the --manifest path; see data/floor-bootstrap.yaml.example",
        )
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as err:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"manifest is not valid YAML: {manifest_path}: {err}",
            remediation="see data/floor-bootstrap.yaml.example for the expected shape",
        ) from err
    if not isinstance(raw, dict):
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"manifest must be a mapping at top-level: {manifest_path}",
            remediation="see data/floor-bootstrap.yaml.example",
        )
    pdf_field = str(raw.get("pdf", "")).strip()
    if not pdf_field:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"manifest is missing the `pdf:` field: {manifest_path}",
            remediation="add `pdf: <path-to-architects.pdf>` at the top",
        )
    pdf_path = Path(pdf_field).expanduser()
    if not pdf_path.is_absolute():
        pdf_path = (manifest_path.parent / pdf_path).resolve()
    floors = raw.get("floors") or []
    if not isinstance(floors, list) or not floors:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"manifest must declare a non-empty `floors:` list: {manifest_path}",
            remediation="see data/floor-bootstrap.yaml.example",
        )
    jobs: list[tuple[str, Path, int | str]] = []
    for idx, entry in enumerate(floors):
        if not isinstance(entry, dict):
            raise OfficeError(
                code=EXIT_USER_ERROR,
                message=f"manifest floors[{idx}] is not a mapping",
                remediation="each entry needs `id:` and `page:`",
            )
        fid = str(entry.get("id", "")).strip()
        page = entry.get("page")
        if not fid:
            raise OfficeError(
                code=EXIT_USER_ERROR,
                message=f"manifest floors[{idx}] is missing `id:`",
                remediation="add `id: <floor-id>`",
            )
        if page is None or page == "":
            raise OfficeError(
                code=EXIT_USER_ERROR,
                message=f"manifest floors[{idx}] (id={fid!r}) is missing `page:`",
                remediation="add `page: <N>` or `page: '<label>'`",
            )
        jobs.append((fid, pdf_path, _coerce_page(page)))
    _ = data_dir  # currently unused; reserved for relative resolution
    return jobs


def _coerce_page(page: object) -> int | str:
    """YAML loads ``page: 8`` as int and ``page: "Fifth Floor"`` as str.

    Pass-through with an explicit non-empty check.
    """
    if isinstance(page, bool):
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"page must be an int or string label; got bool {page!r}",
            remediation="pass --page <N> or --page '<label>'",
        )
    if isinstance(page, int):
        return page
    if isinstance(page, str):
        s = page.strip()
        if s.isdigit():
            return int(s)
        return s
    raise OfficeError(
        code=EXIT_USER_ERROR,
        message=f"page must be an int or string label; got {type(page).__name__}",
        remediation="pass --page <N> or --page '<label>'",
    )


def _resolve_scaffold_floor(floor_id: str, floor_index: dict[Path, Floor]) -> tuple[Floor, Path]:
    """Look up a floor by id; refuse ambiguous matches.

    Floor ids are unique within an office but not globally — two
    offices could declare the same id. Mirrors validate/doctor's
    ambiguity guard so scaffold can't silently write to the wrong
    file. Qodo PR #56.
    """
    matches = [(floor, path) for path, floor in floor_index.items() if floor.id == floor_id]
    if not matches:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"floor id {floor_id!r} is not declared in offices.yaml",
            remediation=(
                "add a floors entry for this id (status: draft is fine) "
                "with at least one cluster, then re-run scaffold"
            ),
        )
    if len(matches) > 1:
        joined = ", ".join(str(p) for _, p in matches)
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"floor id {floor_id!r} is ambiguous — matches: {joined}",
            remediation=(
                "pass --out <path> with the explicit SVG path, or rename one "
                "of the floor ids in offices.yaml"
            ),
        )
    return matches[0]


def _scaffold_out_path(args: argparse.Namespace, existing: Path, data_dir: Path) -> Path:
    """Default to the existing SVG path from offices.yaml; honor --out.

    Relative ``--out`` resolves against ``data_dir``, matching the
    semantics validate/doctor use for relative SVG path arguments.
    Qodo PR #56.
    """
    raw = getattr(args, "out", None)
    if not raw:
        return existing
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = data_dir / p
    return p.resolve()


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

    p_scaff = inner.add_parser(
        "scaffold",
        help="Generate a placeholder SVG (PDF page + 1 example seat + 1 example room).",
        description=(
            "Build a floor scaffold for a declared floor: 1920x1080 viewBox, "
            "embedded PNG of the chosen PDF page, plus one example "
            "<rect class='seat'> and one <polygon class='room'> for the operator "
            "to Ctrl+D-duplicate in Inkscape. The floor must be declared in "
            "offices.yaml (with at least one cluster) before scaffolding."
        ),
    )
    p_scaff.add_argument(
        "floor_id",
        nargs="?",
        help="Floor id from offices.yaml (e.g. 'tlv-floor-3').",
    )
    p_scaff.add_argument("--pdf", help="Path to the architect's PDF.")
    p_scaff.add_argument(
        "--page", help="1-based page number, or text label that appears on one page."
    )
    p_scaff.add_argument(
        "--out", help="Output SVG path (default: floors/<floor-id>.svg from offices.yaml)."
    )
    p_scaff.add_argument(
        "--manifest",
        help="Batch mode: path to a YAML manifest with `pdf:` + `floors: [{id, page}]`.",
    )
    p_scaff.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing SVG. Without this, the verb refuses to clobber.",
    )
    p_scaff.add_argument("--json", action="store_true", help=_HELP_JSON)
    add_data_dir_arg(p_scaff)
    p_scaff.set_defaults(func=cmd_scaffold)

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
