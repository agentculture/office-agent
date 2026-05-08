"""``office floors`` — list and validate floor SVGs against ``offices.yaml``."""

from __future__ import annotations

import argparse
import shutil
from collections import Counter
from pathlib import Path

from office_cli._config import add_data_dir_arg, drive_cache_root, resolve_data_dir
from office_cli.cli._errors import EXIT_USER_ERROR, OfficeError
from office_cli.cli._output import emit_diagnostic, emit_result
from office_cli.floors import (
    Severity,
    copy_layout,
    doctor_svg,
    is_room_id,
    parse_svg,
    scaffold_svg,
    validate_floor,
)
from office_cli.offices import Floor, append_floor_entry, load_offices, update_floor_entry

_HELP_JSON = "Emit structured JSON."
_DOCTOR_HINT_THRESHOLD = 3
_BOOTSTRAP_HINT = "see data/floor-bootstrap.yaml.example"


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
    """Parse the manifest YAML; raise on shape errors.

    Decomposed into small helpers (``_load_manifest``,
    ``_manifest_pdf_path``, ``_manifest_floor_entry``) so each
    validation branch lives by itself; keeps cognitive complexity
    below Sonar's S3776 threshold.
    """
    raw = _load_manifest(manifest_path)
    pdf_path = _manifest_pdf_path(raw, manifest_path)
    floors = raw.get("floors") or []
    if not isinstance(floors, list) or not floors:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"manifest must declare a non-empty `floors:` list: {manifest_path}",
            remediation=_BOOTSTRAP_HINT,
        )
    _ = data_dir  # currently unused; reserved for relative resolution
    return [_manifest_floor_entry(entry, idx, pdf_path) for idx, entry in enumerate(floors)]


def _load_manifest(manifest_path: Path) -> dict:
    """Return the parsed top-level mapping from a manifest YAML."""
    import yaml

    if not manifest_path.is_file():
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"manifest not found: {manifest_path}",
            remediation=f"check the --manifest path; {_BOOTSTRAP_HINT}",
        )
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as err:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"manifest is not valid YAML: {manifest_path}: {err}",
            remediation=f"{_BOOTSTRAP_HINT} for the expected shape",
        ) from err
    if not isinstance(raw, dict):
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"manifest must be a mapping at top-level: {manifest_path}",
            remediation=_BOOTSTRAP_HINT,
        )
    return raw


def _manifest_pdf_path(raw: dict, manifest_path: Path) -> Path:
    """Pull `pdf:` out of the manifest, resolving relative against the manifest dir."""
    pdf_field = _yaml_str(raw.get("pdf"))
    if not pdf_field:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"manifest is missing the `pdf:` field: {manifest_path}",
            remediation="add `pdf: <path-to-architects.pdf>` at the top",
        )
    pdf_path = Path(pdf_field).expanduser()
    if not pdf_path.is_absolute():
        pdf_path = (manifest_path.parent / pdf_path).resolve()
    return pdf_path


def _manifest_floor_entry(entry: object, idx: int, pdf_path: Path) -> tuple[str, Path, int | str]:
    """Validate one `floors[]` entry; return a job tuple."""
    if not isinstance(entry, dict):
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"manifest floors[{idx}] is not a mapping",
            remediation="each entry needs `id:` and `page:`",
        )
    fid = _yaml_str(entry.get("id"))
    if not fid:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"manifest floors[{idx}] is missing `id:`",
            remediation="add `id: <floor-id>`",
        )
    page = entry.get("page")
    if page is None or page == "":
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"manifest floors[{idx}] (id={fid!r}) is missing `page:`",
            remediation="add `page: <N>` or `page: '<label>'`",
        )
    return (fid, pdf_path, _coerce_page(page))


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


def cmd_copy_layout(args: argparse.Namespace) -> int:
    """Copy seats + rooms (geometry only) from one floor's SVG into
    another, renumbering ids per the dst's cluster spec."""
    data_dir = resolve_data_dir(args)
    floor_index = _index_floors(load_offices(data_dir))
    src_floor, src_path = _resolve_scaffold_floor(args.src, floor_index)
    dst_floor, dst_path = _resolve_scaffold_floor(args.dst, floor_index)
    report = copy_layout(
        src_path=src_path,
        src_floor=src_floor,
        dst_path=dst_path,
        dst_floor=dst_floor,
        overwrite=bool(args.overwrite),
    )
    if args.json:
        emit_result(report.to_dict(), json_mode=True)
    else:
        emit_result(
            f"OK   {src_floor.id} -> {dst_floor.id} "
            f"(seats {report.seats_copied}/{report.seat_slots}, "
            f"rooms {report.rooms_copied}/{report.room_slots})",
            json_mode=False,
        )
        for action in report.actions:
            emit_diagnostic(f"  {action}")
        for warning in report.warnings:
            emit_diagnostic(f"  warn: {warning}")
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    """Create a new floor (or many) end-to-end.

    Single-floor mode: ``floors new <id> --pdf <p> --page <N> [--copy-from SRC]``.
    Batch mode: ``floors new --manifest <yaml>`` — manifest declares pdf
    + a list of {id, page} entries, each independently created with
    per-floor atomicity. Failure of one batch entry doesn't roll back
    successful entries.
    """
    data_dir = resolve_data_dir(args)
    if args.manifest:
        return _run_new_batch(args, data_dir)
    return _run_new_single(args, data_dir)


def _run_new_single(args: argparse.Namespace, data_dir: Path) -> int:
    if not args.floor_id:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message="pass a floor id or --manifest <yaml>",
            remediation="example: office floors new tlv-floor-3 --pdf <p> --page 8",
        )
    offices = load_offices(data_dir)
    office_id = _resolve_new_office(args, offices)
    pdf_path = _require_pdf(args)
    page = _coerce_page(args.page) if args.page else _require_page(args)
    src_id = getattr(args, "copy_from", None) or None

    actions, warnings, dst_path = _run_one_new(
        data_dir=data_dir,
        office_id=office_id,
        floor_id=args.floor_id,
        pdf_path=pdf_path,
        page=page,
        src_id=src_id,
    )
    _emit_new_result(args, office_id, args.floor_id, dst_path, actions, warnings)
    return 0


def _run_new_batch(args: argparse.Namespace, data_dir: Path) -> int:
    """Create N floors from a manifest. Per-entry atomicity."""
    jobs = _new_jobs_from_manifest(args, data_dir)
    results: list[dict] = []
    any_failed = False
    for job in jobs:
        try:
            actions, warnings, dst_path = _run_one_new(**job)
            results.append(
                {
                    "floor": job["floor_id"],
                    "office": job["office_id"],
                    "svg": str(dst_path),
                    "ok": True,
                    "actions": actions,
                    "warnings": [w.to_dict() for w in warnings],
                }
            )
        except OfficeError as err:
            any_failed = True
            results.append(
                {
                    "floor": job["floor_id"],
                    "office": job["office_id"],
                    "ok": False,
                    "error": err.message,
                    "remediation": err.remediation,
                }
            )
        except Exception as err:  # noqa: BLE001 — Qodo PR #58: keep per-entry isolation
            # Catch unexpected errors (OSError on write, ET.ParseError on
            # corrupt PDF, KeyError from a malformed manifest field, etc.)
            # so a single bad entry doesn't terminate the whole batch
            # with a traceback.
            any_failed = True
            results.append(
                {
                    "floor": job["floor_id"],
                    "office": job["office_id"],
                    "ok": False,
                    "error": f"{type(err).__name__}: {err}",
                    "remediation": "(unexpected error — see traceback in stderr if needed)",
                }
            )
            # Re-fetch offices.yaml for the next iteration so duplicate-id
            # checks see entries we successfully appended above.
            # (load_offices is called inside _run_one_new -> implicit reload.)
    _emit_batch_result(args, results)
    return EXIT_USER_ERROR if any_failed else 0


def _run_one_new(
    *,
    data_dir: Path,
    office_id: str,
    floor_id: str,
    pdf_path: Path,
    page,
    src_id: str | None,
) -> tuple[list[str], list, Path]:
    """Single-floor create: build entry, render, copy, validate, append YAML.

    Refuses up front if the floor id is already declared anywhere in
    offices.yaml. Resolves ``src_id`` (if any) from the current
    offices state — re-loaded on every call so batch mode sees
    floors created earlier in the same run as candidate copy
    sources. Uses the PR-C `_render_and_validate` flow for full
    per-floor atomicity.
    """
    offices = load_offices(data_dir)
    _ensure_floor_id_not_declared(floor_id, offices)
    src_floor, src_path = _resolve_src_id(src_id, offices)
    new_entry = _build_floor_entry(floor_id, src_floor)
    dst_path = data_dir / new_entry["svg"]
    _ensure_dst_unused(dst_path)
    synthetic_floor = _synth_floor(floor_id, dst_path, new_entry)
    actions, warnings = _render_and_validate(
        synthetic_floor, dst_path, pdf_path, page, src_floor, src_path
    )
    yaml_path = data_dir / "data" / "offices.yaml"
    append_floor_entry(yaml_path, office_id, new_entry)
    actions.append(f"appended {floor_id} under office {office_id}")
    return actions, warnings, dst_path


def _resolve_src_id(src_id: str | None, offices: dict) -> tuple[Floor | None, Path | None]:
    """Resolve a copy-from floor id against the current offices state."""
    if not src_id:
        return None, None
    return _resolve_scaffold_floor(src_id, _index_floors(offices))


def _new_jobs_from_manifest(args: argparse.Namespace, data_dir: Path) -> list[dict]:
    """Parse a manifest into a list of `_run_one_new` kwargs dicts."""
    manifest_path = Path(args.manifest).expanduser()
    raw = _load_manifest(manifest_path)
    pdf_path = _manifest_pdf_path(raw, manifest_path)
    offices = load_offices(data_dir)
    floor_index = _index_floors(offices)
    office_id = _resolve_manifest_office(args, raw, offices)
    default_copy_from = getattr(args, "copy_from", None) or _yaml_str(raw.get("copy_from")) or None
    floors = raw.get("floors") or []
    if not isinstance(floors, list) or not floors:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"manifest must declare a non-empty `floors:` list: {manifest_path}",
            remediation=_BOOTSTRAP_HINT,
        )
    return [
        _build_new_job(entry, idx, pdf_path, office_id, default_copy_from, floor_index, data_dir)
        for idx, entry in enumerate(floors)
    ]


def _build_new_job(
    entry: object,
    idx: int,
    pdf_path: Path,
    office_id: str,
    default_copy_from: str | None,
    floor_index: dict[Path, Floor],
    data_dir: Path,
) -> dict:
    """Validate one manifest entry; return kwargs for `_run_one_new`.

    Note: ``copy_from`` is stored as the source floor id (string),
    NOT resolved to a Floor here. Resolution is deferred to
    `_run_one_new` so a bad copy_from in entry N fails just that
    entry, not the whole batch.
    """
    _ = floor_index  # reserved; per-entry code re-resolves from fresh offices
    if not isinstance(entry, dict):
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"manifest floors[{idx}] is not a mapping",
            remediation="each entry needs `id:` and `page:`",
        )
    fid = _yaml_str(entry.get("id"))
    if not fid:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"manifest floors[{idx}] is missing `id:`",
            remediation="add `id: <floor-id>`",
        )
    page_raw = entry.get("page")
    if page_raw is None or page_raw == "":
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"manifest floors[{idx}] (id={fid!r}) is missing `page:`",
            remediation="add `page: <N>` or `page: '<label>'`",
        )
    per_entry_src = _yaml_str(entry.get("copy_from")) if "copy_from" in entry else ""
    src_id = per_entry_src or default_copy_from or None
    return {
        "data_dir": data_dir,
        "office_id": office_id,
        "floor_id": fid,
        "pdf_path": pdf_path,
        "page": _coerce_page(page_raw),
        "src_id": src_id,
    }


def _resolve_manifest_office(args: argparse.Namespace, raw: dict, offices: dict) -> str:
    """CLI flag > manifest field > single-office auto-detect."""
    if args.office:
        if args.office not in offices:
            known = ", ".join(sorted(offices.keys()))
            raise OfficeError(
                code=EXIT_USER_ERROR,
                message=f"unknown office: {args.office!r}",
                remediation=f"known offices: {known or '(none)'}",
            )
        return args.office
    yaml_office = _yaml_str(raw.get("office"))
    if yaml_office:
        if yaml_office not in offices:
            known = ", ".join(sorted(offices.keys()))
            raise OfficeError(
                code=EXIT_USER_ERROR,
                message=f"manifest references unknown office: {yaml_office!r}",
                remediation=f"known offices: {known or '(none)'}",
            )
        return yaml_office
    if len(offices) == 1:
        return next(iter(offices))
    known = ", ".join(sorted(offices.keys()))
    raise OfficeError(
        code=EXIT_USER_ERROR,
        message="multiple offices declared; manifest needs `office:` or pass --office",
        remediation=f"add `office: <id>` to the manifest top-level (known: {known})",
    )


def _emit_batch_result(args: argparse.Namespace, results: list[dict]) -> None:
    if args.json:
        emit_result({"results": results}, json_mode=True)
        return
    ok_count = sum(1 for r in results if r["ok"])
    fail_count = len(results) - ok_count
    emit_result(
        f"batch: {ok_count} ok, {fail_count} failed (of {len(results)})",
        json_mode=False,
    )
    for r in results:
        if r["ok"]:
            emit_diagnostic(f"  OK   {r['floor']} ({r['svg']})")
        else:
            emit_diagnostic(f"  FAIL {r['floor']}: {r['error']}")
            if r.get("remediation"):
                emit_diagnostic(f"       hint: {r['remediation']}")


def _ensure_dst_unused(dst_path: Path) -> None:
    if dst_path.exists():
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"refusing to overwrite existing SVG: {dst_path}",
            remediation=(
                "delete the file first, or pick a different floor id "
                "(refusing to silently overwrite operator state)"
            ),
        )


def _synth_floor(floor_id: str, dst_path: Path, entry: dict) -> Floor:
    return Floor(
        id=floor_id,
        svg=dst_path,
        clusters=_synth_clusters(entry["clusters"]),
        rooms=_synth_rooms(entry["rooms"]),
        status="draft",
    )


def _render_and_validate(
    synthetic_floor: Floor,
    dst_path: Path,
    pdf_path: Path,
    page,
    src_floor: Floor | None,
    src_path: Path | None,
) -> tuple[list[str], list]:
    """Render scaffold + optional copy-layout + validate; roll back on failure."""
    actions = ["scaffolded SVG"]
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        svg_bytes = scaffold_svg(floor=synthetic_floor, pdf=pdf_path, page=page)
        dst_path.write_bytes(svg_bytes)
        if src_floor is not None and src_path is not None:
            copy_layout(
                src_path=src_path,
                src_floor=src_floor,
                dst_path=dst_path,
                dst_floor=synthetic_floor,
            )
            actions.append(f"copied layout from {src_floor.id}")
        issues = validate_floor(parse_svg(dst_path), synthetic_floor)
    except Exception:
        if dst_path.exists():
            dst_path.unlink()
        raise

    errors = [i for i in issues if i.severity is Severity.ERROR]
    warnings = [i for i in issues if i.severity is Severity.WARNING]
    if errors:
        dst_path.unlink()
        for err in errors:
            emit_diagnostic(f"  error [{err.rule}]: {err.message}")
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=(
                f"generated SVG for {synthetic_floor.id!r} has {len(errors)} "
                "validation error(s); rolled back, no YAML written"
            ),
            remediation="fix the source layout (or pick a different page) and re-run",
        )
    return actions, warnings


def _emit_new_result(
    args: argparse.Namespace,
    office_id: str,
    floor_id: str,
    dst_path: Path,
    actions: list[str],
    warnings: list,
) -> None:
    payload = {
        "office": office_id,
        "floor": floor_id,
        "svg": str(dst_path),
        "actions": actions,
        "errors": [],
        "warnings": [i.to_dict() for i in warnings],
    }
    if args.json:
        emit_result(payload, json_mode=True)
        return
    emit_result(f"OK   {floor_id} ({dst_path})", json_mode=False)
    for action in actions:
        emit_diagnostic(f"  {action}")
    for warn in warnings:
        emit_diagnostic(f"  warn  [{warn.rule}]: {warn.message}")
    emit_diagnostic(
        "  next: trace seats in Inkscape, then `office floors doctor "
        f"{floor_id}`, then upload to Drive."
    )


def _synth_clusters(spec: object) -> dict:
    """Materialize the dict-of-Cluster used by `Floor` from a YAML-shape spec."""
    from office_cli.offices._models import Cluster

    out: dict = {}
    if isinstance(spec, dict):
        for letter, sub in spec.items():
            if isinstance(sub, dict):
                out[letter] = Cluster(
                    letter=letter,
                    capacity=int(sub.get("capacity", 1)),
                    type=str(sub.get("type", "open-space")),
                )
    return out


def _synth_rooms(spec: object) -> dict:
    """Materialize the dict-of-Room used by `Floor` from a YAML-shape spec."""
    from office_cli.offices._models import Room

    out: dict = {}
    if isinstance(spec, dict):
        for rid, sub in spec.items():
            if isinstance(sub, dict):
                out[rid] = Room(
                    id=rid,
                    name=str(sub.get("name", rid)),
                    type=str(sub.get("type", "meeting")),
                    capacity=int(sub.get("capacity", 0)),
                )
    return out


def _resolve_new_office(args: argparse.Namespace, offices: dict) -> str:
    """Pick the office for a new floor.

    Auto-detects when offices.yaml has exactly one office; required
    otherwise.
    """
    if args.office:
        if args.office not in offices:
            known = ", ".join(sorted(offices.keys()))
            raise OfficeError(
                code=EXIT_USER_ERROR,
                message=f"unknown office: {args.office!r}",
                remediation=f"known offices: {known or '(none)'}",
            )
        return args.office
    if len(offices) == 1:
        return next(iter(offices))
    known = ", ".join(sorted(offices.keys()))
    raise OfficeError(
        code=EXIT_USER_ERROR,
        message="multiple offices declared; --office is required",
        remediation=f"pass --office <id> (known: {known})",
    )


def _ensure_floor_id_not_declared(floor_id: str, offices: dict) -> None:
    for office in offices.values():
        if floor_id in office.floors:
            raise OfficeError(
                code=EXIT_USER_ERROR,
                message=f"floor id {floor_id!r} is already declared under office {office.id!r}",
                remediation=(
                    "delete the existing entry first, or pick a different id "
                    "(refusing to silently overwrite)"
                ),
            )


def _resolve_optional_src(
    args: argparse.Namespace, floor_index: dict[Path, Floor]
) -> tuple[Floor | None, Path | None]:
    src_id = getattr(args, "copy_from", None)
    if not src_id:
        return None, None
    src_floor, src_path = _resolve_scaffold_floor(src_id, floor_index)
    return src_floor, src_path


def _require_pdf(args: argparse.Namespace) -> Path:
    if not args.pdf:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message="--pdf is required",
            remediation="pass --pdf <path-to-architects.pdf>",
        )
    return Path(args.pdf).expanduser()


def _require_page(args: argparse.Namespace) -> int | str:
    if not args.page:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message="--page is required",
            remediation="pass --page <N> (1-based) or --page <label>",
        )
    return _coerce_page(args.page)


def _yaml_str(value: object) -> str:
    """Coerce a YAML-loaded value to a stripped string.

    Critical detail: YAML's ``null`` (or a missing key with a ``None``
    fallback) loads as Python ``None`` — and ``str(None) == 'None'``,
    which is truthy. Without this helper, ``copy_from: null`` /
    ``office: null`` / ``pdf: null`` would each silently become the
    literal string ``"None"`` and produce confusing downstream errors
    ("unknown office: 'None'" rather than "missing field"). Qodo PR #58.
    """
    if value is None:
        return ""
    return str(value).strip()


def _retarget_room_id(rid: str, dst_floor_num: str) -> str:
    """Replace the floor prefix in a `<floor>.<NN>` room id.

    ``5.18`` (floor-5 stencil) → ``3.18`` (floor-3 destination).
    Non-conforming ids (custom strings, legacy formats) pass through
    unchanged so we never mangle data we don't recognize.
    """
    if not is_room_id(rid):
        return rid
    suffix = rid.split(".", 1)[1]
    return f"{dst_floor_num}.{suffix}"


def _build_floor_entry(floor_id: str, src_floor: Floor | None) -> dict:
    """Shape the dict consumed by ``append_floor_entry``.

    Inherits cluster + room spec from ``src_floor`` when given (so a
    --copy-from creates an offices.yaml entry that fits the source's
    layout). Without it, falls back to a placeholder T:1 cluster.

    Room ids are **retargeted** to the destination floor's number so
    that copying floor-5's ``5.18`` produces floor-3's ``3.18``,
    matching the architect's per-floor numbering convention. Seats
    don't need this here — they're renumbered later by ``copy_layout``
    via ``_seat_ids_for(dst_floor.number, ...)``.
    """
    dst_num = floor_id.rsplit("-", 1)[-1]
    if src_floor is not None:
        clusters = {
            letter: {"capacity": cluster.capacity, "type": cluster.type}
            for letter, cluster in src_floor.clusters.items()
        }
        rooms = {
            _retarget_room_id(rid, dst_num): {
                "name": r.name,
                "type": r.type,
                "capacity": r.capacity,
            }
            for rid, r in src_floor.rooms.items()
        }
    else:
        clusters = {"T": {"capacity": 1, "type": "open-space"}}
        rooms = {}
    return {
        "id": floor_id,
        "svg": f"floors/{floor_id}.svg",
        "status": "draft",
        "clusters": clusters,
        "rooms": rooms,
    }


def cmd_doctor(args: argparse.Namespace) -> int:
    """Diagnose-and-fix floor SVGs.

    Default (keep-all): just renumber the ids — preserves every traced
    shape, auto-grows offices.yaml's cluster capacities and rooms list
    to match.

    ``--prune``: drop off-page shapes + dedupe near-duplicates +
    renumber per the existing cluster spec (drops excess). Original
    PR-A behavior, opt-in.
    """
    data_dir = resolve_data_dir(args)
    offices = load_offices(data_dir)
    floor_index = _index_floors(offices)
    targets = _resolve_targets(args, floor_index, data_dir)
    prune = bool(getattr(args, "prune", False))
    payload: list[dict[str, object]] = []
    for target in targets:
        floor = floor_index.get(target)
        if floor is None:
            raise OfficeError(
                code=EXIT_USER_ERROR,
                message=f"SVG {target} is not declared in offices.yaml",
                remediation="add a floors entry pointing at this SVG, or pass an SVG that is",
            )
        report = doctor_svg(target, floor, dry_run=bool(args.dry_run), prune=prune)
        # Auto-grow offices.yaml when keep-all mode produced more
        # shapes than the declared spec covers. Skipped on dry-run and
        # in prune mode (where nothing grew).
        if not args.dry_run and not prune:
            _maybe_autogrow_yaml(data_dir, offices, floor, report)
        payload.append(report.to_dict())
    if args.json:
        emit_result({"results": payload}, json_mode=True)
    else:
        _print_doctor_text(payload)
    return 0


def _maybe_autogrow_yaml(
    data_dir: Path,
    offices: dict,
    floor: Floor,
    report,
) -> None:
    """Update offices.yaml if the doctor's new spec differs from declared.

    Issue #54 follow-up. Bumps cluster capacities and expands the rooms
    list when keep-all mode produced shapes beyond declared capacity.
    Default room metadata (`name`, `type`, `capacity`) is filled in for
    newly-added rooms; existing rooms keep their declared metadata.
    """
    declared_caps = {letter: c.capacity for letter, c in floor.clusters.items()}
    declared_rooms = list(floor.rooms.keys())
    if report.new_clusters == declared_caps and report.new_rooms == declared_rooms:
        return
    # Find which office this floor belongs to.
    office_id = next((oid for oid, o in offices.items() if floor.id in o.floors), None)
    if office_id is None:
        return  # shouldn't happen if floor came from offices
    yaml_path = data_dir / "data" / "offices.yaml"
    new_clusters_spec = {
        letter: {
            "capacity": cap,
            "type": (floor.clusters[letter].type if letter in floor.clusters else "open-space"),
        }
        for letter, cap in report.new_clusters.items()
    }
    new_rooms_spec = {
        rid: (
            {
                "name": floor.rooms[rid].name,
                "type": floor.rooms[rid].type,
                "capacity": floor.rooms[rid].capacity,
            }
            if rid in floor.rooms
            else {"name": f"Room {rid}", "type": "meeting", "capacity": 4}
        )
        for rid in report.new_rooms
    }
    update_floor_entry(
        yaml_path,
        office_id,
        floor.id,
        clusters=new_clusters_spec,
        rooms=new_rooms_spec,
    )
    report.actions.append(f"updated offices.yaml: {floor.id} clusters/rooms auto-grown")


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
        "--prune",
        action="store_true",
        help=(
            "Aggressive cleanup: drop off-page shapes + dedupe near-duplicates "
            "+ drop excess beyond declared capacity. Default keeps everything "
            "and just fixes the ids (auto-growing offices.yaml to match)."
        ),
    )
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

    p_copy = inner.add_parser(
        "copy-layout",
        help="Copy seats+rooms geometry from one floor to another (renumbering ids).",
        description=(
            "Copy <rect class='seat'> and <polygon class='room'> elements "
            "from a clean source floor's SVG into a destination scaffold. "
            "The destination's embedded background and viewBox are preserved; "
            "ids are renumbered per the dst floor's cluster spec in offices.yaml."
        ),
    )
    p_copy.add_argument("src", help="Source floor id (e.g. 'tlv-floor-5').")
    p_copy.add_argument("dst", help="Destination floor id (e.g. 'tlv-floor-3').")
    p_copy.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow copying onto a non-draft (status: active) destination.",
    )
    p_copy.add_argument("--json", action="store_true", help=_HELP_JSON)
    add_data_dir_arg(p_copy)
    p_copy.set_defaults(func=cmd_copy_layout)

    p_new = inner.add_parser(
        "new",
        help="Create a new floor: append offices.yaml entry + scaffold SVG.",
        description=(
            "End-to-end create for a new floor. Appends the offices.yaml entry "
            "(status: draft), scaffolds the SVG from the chosen PDF page, and "
            "optionally overlays seats+rooms from an existing floor."
        ),
    )
    p_new.add_argument(
        "floor_id",
        nargs="?",
        help="New floor id (e.g. 'tlv-floor-3'). Required unless --manifest is passed.",
    )
    p_new.add_argument(
        "--manifest",
        help="Batch mode: YAML manifest with pdf + floors[{id, page}] + optional copy_from.",
    )
    p_new.add_argument("--pdf", help="Path to the architect's PDF.")
    p_new.add_argument(
        "--page", help="1-based page number, or text label that appears on one page."
    )
    p_new.add_argument(
        "--office",
        help="Office id (required when offices.yaml declares multiple offices).",
    )
    p_new.add_argument(
        "--copy-from",
        dest="copy_from",
        help="Existing floor id whose layout (and cluster spec) to inherit.",
    )
    p_new.add_argument("--json", action="store_true", help=_HELP_JSON)
    add_data_dir_arg(p_new)
    p_new.set_defaults(func=cmd_new)

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
