"""Eager hydration of a Drive-hosted office tree into a local cache dir.

When ``OFFICE_DRIVE_ROOT`` is set, :func:`hydrate_data_dir` pulls
``offices.yaml`` + every declared SVG into ``<cache_root>/<root-id>/``,
returning a path that mirrors the on-disk data-dir layout
(``data/``, ``floors/``, ``seats/``). Downstream code reads from this
path as if it were a regular checkout, so the rest of the pipeline
(``load_offices``, ``parse_svg``, ``resolve_storage``) is unchanged.

Drive's authoring layout uses one folder per office, named so the
folder name ends with ``(<office-id>)``::

    <Org Drive>/Office Maps/                ← OFFICE_DRIVE_ROOT
      offices.yaml
      Tel Aviv (tlv)/
        tlv-floor-5.svg
      Frankfurt (fc)/
        fc-floor-2.svg

The hydrator translates Drive's bare-filename ``svg`` fields into the
``floors/<filename>`` relative paths the existing YAML resolver
already understands (``office_cli/offices/_yaml.py``).

Warm cache: if every required file (``data/offices.yaml`` + each
referenced SVG) is present locally and its meta age is below the TTL,
:func:`hydrate_data_dir` returns without making any Drive API calls
— including folder listings.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Optional

import yaml

from office_cli.cli._errors import EXIT_ENV_ERROR, EXIT_USER_ERROR, OfficeError
from office_cli.drive._cache import CacheMeta
from office_cli.drive._client import DriveClient, DriveEntry, GoogleDriveClient

_OFFICES_YAML = "offices.yaml"
_YAML_REL = "data/offices.yaml"
_OFFICE_ID_RE = re.compile(r"\(([a-z0-9-]+)\)\s*$")


def hydrate_data_dir(
    root_folder_id: str,
    *,
    credentials_path: Path,
    cache_root: Path,
    ttl_seconds: int = 300,
    client: Optional[DriveClient] = None,
) -> Path:
    """Hydrate a Drive root into a local cache dir; return the cache path.

    The returned path has the on-disk data-dir layout
    (``data/offices.yaml``, ``floors/<svg>``, ``seats/``) so callers
    can pass it straight to :func:`office_cli.offices.load_offices`.

    ``client`` is injectable so tests can drive the hydrator with an
    in-memory fake instead of the real Drive API.
    """
    if not root_folder_id:
        raise OfficeError(
            code=EXIT_ENV_ERROR,
            message="OFFICE_DRIVE_ROOT is empty",
            remediation="set OFFICE_DRIVE_ROOT to a Google Drive folder id",
        )

    cache_dir = cache_root / root_folder_id
    _ensure_cache_layout(cache_dir)
    meta = CacheMeta(cache_dir)

    if _is_warm_cache_complete(cache_dir, meta, ttl_seconds):
        return cache_dir

    drive: DriveClient = client or GoogleDriveClient(credentials_path)
    _hydrate_from_drive(drive, root_folder_id, cache_dir, meta, ttl_seconds)
    return cache_dir


# -- Cache layout + warm-path -------------------------------------------------


def _ensure_cache_layout(cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "data").mkdir(exist_ok=True)
    (cache_dir / "floors").mkdir(exist_ok=True)
    (cache_dir / "seats").mkdir(exist_ok=True)


def _is_warm_cache_complete(cache_dir: Path, meta: CacheMeta, ttl: int) -> bool:
    """Return True iff the YAML and every referenced SVG are fresh+present.

    A True result means :func:`hydrate_data_dir` can skip Drive entirely
    — no folder listings, no downloads. Any structural issue with the
    cached YAML (missing offices list, non-mapping entries, missing svg
    field, missing local file, stale meta) returns False so the caller
    falls through to a full hydrate that will surface the error from
    Drive's authoritative copy.
    """
    yaml_path = cache_dir / _YAML_REL
    if not (yaml_path.is_file() and meta.is_fresh(_YAML_REL, ttl)):
        return False
    try:
        data = _load_yaml(yaml_path)
    except OfficeError:
        return False
    offices_raw = data.get("offices")
    if not isinstance(offices_raw, list):
        return False
    for office in offices_raw:
        if not isinstance(office, dict):
            return False
        floors_raw = office.get("floors") or []
        if not isinstance(floors_raw, list):
            return False
        for floor in floors_raw:
            if not isinstance(floor, dict):
                return False
            svg_rel = str(floor.get("svg", "")).strip()
            if not svg_rel:
                return False
            local = cache_dir / svg_rel
            if not (local.is_file() and meta.is_fresh(svg_rel, ttl)):
                return False
    return True


# -- Drive hydration ----------------------------------------------------------


def _hydrate_from_drive(
    drive: DriveClient,
    root_folder_id: str,
    cache_dir: Path,
    meta: CacheMeta,
    ttl: int,
) -> None:
    yaml_cache = cache_dir / _YAML_REL
    root_entries = drive.list_folder(root_folder_id)
    yaml_entry = _find_root_yaml(root_entries)
    if not (meta.is_fresh(_YAML_REL, ttl) and yaml_cache.is_file()):
        yaml_cache.write_bytes(drive.download_file(yaml_entry.id))
        meta.record(_YAML_REL)

    yaml_data = _load_yaml(yaml_cache)
    offices_raw = _validate_offices_list(yaml_data)
    folders_by_name = _group_by_name(root_entries, lambda e: e.is_folder)

    for idx, office in enumerate(offices_raw):
        _hydrate_office(office, idx, drive, folders_by_name, cache_dir, meta, ttl)

    yaml_data["offices"] = offices_raw
    with yaml_cache.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(yaml_data, fh, sort_keys=False, allow_unicode=True)


def _hydrate_office(
    office: object,
    idx: int,
    drive: DriveClient,
    folders_by_name: dict[str, list[DriveEntry]],
    cache_dir: Path,
    meta: CacheMeta,
    ttl: int,
) -> None:
    if not isinstance(office, dict):
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"office entry at index {idx} is not a mapping",
            remediation="see data/offices.yaml.example for the expected shape",
        )
    oid = str(office.get("id", "")).strip()
    if not oid:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"office entry at index {idx} is missing an `id`",
            remediation="add `id: <short-name>` to the office entry",
        )
    folder_entry = _match_office_folder(folders_by_name, oid)
    floor_entries = drive.list_folder(folder_entry.id)
    files_by_name = _group_by_name(floor_entries, lambda e: not e.is_folder)
    floors_raw = office.get("floors") or []
    rewritten: list[object] = []
    for fidx, floor in enumerate(floors_raw):
        rewritten.append(
            _hydrate_floor(
                floor, fidx, oid, folder_entry, files_by_name, drive, cache_dir, meta, ttl
            )
        )
    office["floors"] = rewritten


def _hydrate_floor(
    floor: object,
    idx: int,
    office_id: str,
    folder_entry: DriveEntry,
    files_by_name: dict[str, list[DriveEntry]],
    drive: DriveClient,
    cache_dir: Path,
    meta: CacheMeta,
    ttl: int,
) -> dict:
    if not isinstance(floor, dict):
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=(f"office {office_id!r}: floor entry at index {idx} is not a mapping"),
            remediation="see data/offices.yaml.example for the expected shape",
        )
    fid = str(floor.get("id", "")).strip()
    if not fid:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"office {office_id!r}: floor entry at index {idx} is missing an `id`",
            remediation="add `id: <floor-id>` to the floor entry",
        )
    svg_field = str(floor.get("svg", f"{fid}.svg")).strip()
    svg_name = svg_field.split("/")[-1]
    if not svg_name:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"floor {fid!r}: empty `svg` field in offices.yaml",
            remediation="set `svg:` to the SVG filename in the office folder",
        )
    entry = _resolve_unique_file(files_by_name, svg_name, fid, folder_entry.name)
    rel = f"floors/{svg_name}"
    local = cache_dir / rel
    if not (meta.is_fresh(rel, ttl) and local.is_file()):
        local.write_bytes(drive.download_file(entry.id))
        meta.record(rel)
    new_floor = dict(floor)
    new_floor["svg"] = rel
    return new_floor


# -- Drive entry indexing -----------------------------------------------------


def _group_by_name(
    entries: list[DriveEntry], predicate: Callable[[DriveEntry], bool]
) -> dict[str, list[DriveEntry]]:
    """Group entries by name into lists, after filtering by ``predicate``.

    Drive permits same-name siblings; indexing by a plain ``dict`` would
    silently drop duplicates. Lookups (``_resolve_unique_file``,
    ``_match_office_folder``) raise ``OfficeError`` on collisions instead.
    """
    out: dict[str, list[DriveEntry]] = {}
    for e in entries:
        if predicate(e):
            out.setdefault(e.name, []).append(e)
    return out


def _resolve_unique_file(
    files_by_name: dict[str, list[DriveEntry]],
    name: str,
    floor_id: str,
    folder_name: str,
) -> DriveEntry:
    matches = files_by_name.get(name) or []
    if not matches:
        present = sorted(files_by_name.keys())
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=(
                f"floor {floor_id!r}: SVG {name!r} not found in office folder " f"{folder_name!r}"
            ),
            remediation=(
                "upload the SVG to that folder, or fix the `svg:` field in "
                "offices.yaml. Files present: "
                f"{', '.join(present) if present else '(none)'}"
            ),
        )
    if len(matches) > 1:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=(
                f"floor {floor_id!r}: multiple files named {name!r} in office "
                f"folder {folder_name!r}"
            ),
            remediation="rename or remove duplicates so only one file matches",
        )
    return matches[0]


def _find_root_yaml(entries: list[DriveEntry]) -> DriveEntry:
    matches = [e for e in entries if e.name == _OFFICES_YAML and not e.is_folder]
    if not matches:
        raise OfficeError(
            code=EXIT_ENV_ERROR,
            message=f"{_OFFICES_YAML} not found at the root of OFFICE_DRIVE_ROOT",
            remediation=(
                "upload offices.yaml to the folder pointed at by "
                "OFFICE_DRIVE_ROOT, and ensure the service account has access"
            ),
        )
    if len(matches) > 1:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"multiple {_OFFICES_YAML} entries at OFFICE_DRIVE_ROOT",
            remediation="remove duplicates so only one offices.yaml remains",
        )
    return matches[0]


def _match_office_folder(
    folders_by_name: dict[str, list[DriveEntry]], office_id: str
) -> DriveEntry:
    matches: list[DriveEntry] = []
    for name, entries in folders_by_name.items():
        m = _OFFICE_ID_RE.search(name)
        if m and m.group(1) == office_id:
            matches.extend(entries)
    if not matches:
        present = sorted(folders_by_name.keys())
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=(
                f"no Drive folder matches office id {office_id!r} "
                f"(expected a folder name ending with '({office_id})')"
            ),
            remediation=(
                "create a folder under OFFICE_DRIVE_ROOT named like "
                f"'Office Name ({office_id})'. Folders present: "
                f"{', '.join(present) if present else '(none)'}"
            ),
        )
    if len(matches) > 1:
        names = ", ".join(e.name for e in matches)
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"multiple Drive folders match office id {office_id!r}: {names}",
            remediation="rename or remove duplicates so only one folder matches",
        )
    return matches[0]


# -- YAML helpers -------------------------------------------------------------


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        try:
            raw = yaml.safe_load(fh) or {}
        except yaml.YAMLError as err:
            raise OfficeError(
                code=EXIT_USER_ERROR,
                message=f"offices.yaml in Drive is not valid YAML: {err}",
                remediation="fix the YAML syntax in Drive and rerun",
            ) from err
    if not isinstance(raw, dict):
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message="offices.yaml in Drive must be a mapping at the top level",
            remediation="see data/offices.yaml.example for the expected shape",
        )
    return raw


def _validate_offices_list(yaml_data: dict) -> list:
    offices_raw = yaml_data.get("offices")
    if not isinstance(offices_raw, list):
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message="offices.yaml in Drive must contain a top-level `offices:` list",
            remediation="see data/offices.yaml.example for the expected shape",
        )
    return offices_raw
