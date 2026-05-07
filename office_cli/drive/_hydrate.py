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
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import yaml

from office_cli.cli._errors import EXIT_ENV_ERROR, EXIT_USER_ERROR, OfficeError
from office_cli.drive._cache import CacheMeta
from office_cli.drive._client import DriveClient, DriveEntry, GoogleDriveClient

_OFFICES_YAML = "offices.yaml"
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
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "data").mkdir(exist_ok=True)
    (cache_dir / "floors").mkdir(exist_ok=True)
    (cache_dir / "seats").mkdir(exist_ok=True)

    drive: DriveClient = client or GoogleDriveClient(credentials_path)
    meta = CacheMeta(cache_dir)

    root_entries = drive.list_folder(root_folder_id)
    yaml_entry = _find_root_yaml(root_entries)

    yaml_rel = "data/offices.yaml"
    yaml_cache = cache_dir / yaml_rel
    if not (meta.is_fresh(yaml_rel, ttl_seconds) and yaml_cache.is_file()):
        yaml_cache.write_bytes(drive.download_file(yaml_entry.id))
        meta.record(yaml_rel)

    yaml_data = _load_yaml(yaml_cache)
    offices_raw = yaml_data.get("offices")
    if not isinstance(offices_raw, list):
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message="offices.yaml in Drive must contain a top-level `offices:` list",
            remediation="see data/offices.yaml.example for the expected shape",
        )

    folder_index = {e.name: e for e in root_entries if e.is_folder}
    for office in offices_raw:
        if not isinstance(office, dict):
            continue
        oid = str(office.get("id", "")).strip()
        if not oid:
            continue
        folder_entry = _match_office_folder(folder_index, oid)
        floor_entries = drive.list_folder(folder_entry.id)
        floor_index = {e.name: e for e in floor_entries if not e.is_folder}
        floors_raw = office.get("floors") or []
        rewritten: list[object] = []
        for floor in floors_raw:
            if not isinstance(floor, dict):
                rewritten.append(floor)
                continue
            fid = str(floor.get("id", "")).strip()
            svg_field = str(floor.get("svg", f"{fid}.svg")).strip()
            # Drive YAML uses bare filenames; tolerate "floors/<name>" too.
            svg_name = svg_field.split("/")[-1]
            if not svg_name:
                raise OfficeError(
                    code=EXIT_USER_ERROR,
                    message=f"floor {fid!r}: empty `svg` field in offices.yaml",
                    remediation="set `svg:` to the SVG filename in the office folder",
                )
            entry = floor_index.get(svg_name)
            if entry is None:
                present = sorted(floor_index.keys())
                raise OfficeError(
                    code=EXIT_USER_ERROR,
                    message=(
                        f"floor {fid!r}: SVG {svg_name!r} not found in "
                        f"office folder {folder_entry.name!r}"
                    ),
                    remediation=(
                        "upload the SVG to that folder, or fix the `svg:` "
                        "field in offices.yaml. Files present: "
                        f"{', '.join(present) if present else '(none)'}"
                    ),
                )
            rel = f"floors/{svg_name}"
            local = cache_dir / rel
            if not (meta.is_fresh(rel, ttl_seconds) and local.is_file()):
                local.write_bytes(drive.download_file(entry.id))
                meta.record(rel)
            new_floor = dict(floor)
            new_floor["svg"] = rel
            rewritten.append(new_floor)
        office["floors"] = rewritten

    yaml_data["offices"] = offices_raw
    with yaml_cache.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(yaml_data, fh, sort_keys=False, allow_unicode=True)

    return cache_dir


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


def _match_office_folder(folder_index: dict[str, DriveEntry], office_id: str) -> DriveEntry:
    matches: list[DriveEntry] = []
    for name, entry in folder_index.items():
        m = _OFFICE_ID_RE.search(name)
        if m and m.group(1) == office_id:
            matches.append(entry)
    if not matches:
        present = sorted(folder_index.keys())
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
