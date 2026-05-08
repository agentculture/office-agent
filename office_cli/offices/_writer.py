"""Append a new floor entry to ``data/offices.yaml`` without rewriting the file.

PyYAML's :func:`yaml.safe_dump` strips comments and reorders fields,
which would mangle the carefully-commented ``data/offices.yaml``. This
module instead does a **textual splice**: parse the file once with
PyYAML to validate structure, locate the target office's ``floors:``
list in the source text, and insert a new entry while preserving
everything else byte-for-byte.

The verb ``office floors new`` (issue #54 follow-up) calls
:func:`append_floor_entry` to add a draft floor without operators
having to hand-edit the YAML.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping

import yaml

from office_cli.cli._errors import EXIT_USER_ERROR, OfficeError

_DEFAULT_INDENT = "      "  # 6 spaces — list items under offices[].floors


def append_floor_entry(
    yaml_path: Path,
    office_id: str,
    floor: Mapping[str, object],
) -> None:
    """Append a floor entry under ``offices[id=office_id].floors``.

    ``floor`` is a mapping with at least ``id`` and ``svg`` keys, plus
    optional ``status``, ``clusters``, ``rooms``. Validation rules:

    - ``yaml_path`` must be valid YAML and have a top-level
      ``offices:`` list.
    - ``office_id`` must match an existing office.
    - ``floor['id']`` must not already be declared under that office.

    The function preserves comments, trailing whitespace, and the
    rest of the file.
    """
    # Defend against path traversal: the helper is only ever called for
    # ``<data_dir>/data/offices.yaml`` (per `cmd_new` plumbing). Refuse
    # if the caller passes anything else — keeps Sonar S2083's taint
    # analysis happy and protects callers from accidentally pointing
    # the writer at a system file.
    if yaml_path.name != "offices.yaml":
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"refusing to write a non-offices.yaml file: {yaml_path}",
            remediation="pass a path whose final component is `offices.yaml`",
        )
    if not yaml_path.is_file():
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"offices.yaml not found: {yaml_path}",
            remediation="check the --data-dir or run from the repo root",
        )
    fid = str(floor.get("id", "")).strip()
    if not fid:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message="floor entry is missing `id`",
            remediation="pass a floor dict with at least `id` and `svg`",
        )
    text = yaml_path.read_text(encoding="utf-8")
    parsed = _parse_offices(text, yaml_path)
    office = _find_office(parsed, office_id, yaml_path)
    _ensure_floor_id_unique(office, fid, office_id)

    # Locate the matching `- id: <office_id>` block and the end of its
    # `floors:` child list in the source text. The item indent is
    # discovered from the file (Qodo PR #57: don't hardcode 6 spaces).
    insertion_point, item_indent = _find_insertion_point(text, office_id, yaml_path)
    new_block = _format_floor_block(floor, item_indent=item_indent)
    new_text = text[:insertion_point] + new_block + text[insertion_point:]
    yaml_path.write_text(new_text, encoding="utf-8")


def _parse_offices(text: str, path: Path) -> list[dict]:
    try:
        raw = yaml.safe_load(text) or {}
    except yaml.YAMLError as err:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"offices.yaml is not valid YAML: {path}: {err}",
            remediation="fix the syntax error and rerun",
        ) from err
    offices = raw.get("offices") if isinstance(raw, dict) else None
    if not isinstance(offices, list):
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"offices.yaml is missing top-level `offices:` list: {path}",
            remediation="see data/offices.yaml.example for the expected shape",
        )
    return offices


def _find_office(offices: list[dict], office_id: str, path: Path) -> dict:
    for entry in offices:
        if isinstance(entry, dict) and str(entry.get("id", "")).strip() == office_id:
            return entry
    known = ", ".join(sorted(str(e.get("id", "")) for e in offices if isinstance(e, dict)))
    raise OfficeError(
        code=EXIT_USER_ERROR,
        message=f"unknown office {office_id!r} in {path}",
        remediation=f"known offices: {known or '(none)'}",
    )


def _ensure_floor_id_unique(office: dict, floor_id: str, office_id: str) -> None:
    floors = office.get("floors") or []
    if not isinstance(floors, list):
        return
    for entry in floors:
        if isinstance(entry, dict) and str(entry.get("id", "")).strip() == floor_id:
            raise OfficeError(
                code=EXIT_USER_ERROR,
                message=f"floor id {floor_id!r} already declared under office {office_id!r}",
                remediation=(
                    "delete the existing entry first, or pick a different "
                    "floor id (refusing to silently overwrite)"
                ),
            )


def _find_insertion_point(text: str, office_id: str, path: Path) -> tuple[int, str]:
    """Return ``(byte_offset, item_indent)`` for the new floor entry.

    Walks the source line-by-line:

    1. Find ``- id: <office_id>`` (start of the matching office block).
    2. Inside that block, find ``floors:``.
    3. Scan forward to the last child entry of that floors list.
    4. Insert at the end of that last entry, and report the indent
       used by existing list items so the caller can match it.
    """
    lines = text.splitlines(keepends=True)
    office_line, office_indent = _locate_office_block(lines, office_id, path)
    floors_line, floors_indent = _locate_floors_key(
        lines, office_line, office_indent, office_id, path
    )
    item_indent = " " * (floors_indent + 2)
    return _scan_to_block_end(lines, floors_line, item_indent + "- "), item_indent


def _locate_office_block(lines: list[str], office_id: str, path: Path) -> tuple[int, int]:
    needle = re.compile(r"^(\s*)- id:\s*" + re.escape(office_id) + r"\s*$")
    for i, line in enumerate(lines):
        m = needle.match(line)
        if m:
            return i, len(m.group(1))
    raise OfficeError(
        code=EXIT_USER_ERROR,
        message=(
            f"could not locate the `- id: {office_id}` line in {path}; " "structure is unusual"
        ),
        remediation="hand-edit data/offices.yaml or simplify its layout",
    )


def _locate_floors_key(
    lines: list[str], start: int, office_indent: int, office_id: str, path: Path
) -> tuple[int, int]:
    inner_indent = office_indent + 2  # `- ` makes children indent 2 deeper
    pattern = re.compile(r"^" + " " * inner_indent + r"floors:\s*$")
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if pattern.match(line):
            return i, inner_indent
        # If we hit another office at the same depth, give up.
        if re.match(r"^" + " " * office_indent + r"- id:", line):
            break
    raise OfficeError(
        code=EXIT_USER_ERROR,
        message=(
            f"office {office_id!r} has no `floors:` block in {path}; "
            "add an empty `floors:` line first"
        ),
        remediation="hand-edit offices.yaml to declare `floors:`",
    )


def _scan_to_block_end(lines: list[str], floors_line: int, item_prefix: str) -> int:
    """Find the byte offset to insert at the end of a YAML list block."""
    last_item_end_line = floors_line  # if floors list is empty, insert right after
    for i in range(floors_line + 1, len(lines)):
        if _line_belongs_to_block(lines[i], item_prefix):
            last_item_end_line = i
            continue
        if lines[i].strip() == "":
            continue
        # Anything else = end of the floors list.
        break
    return sum(len(line) for line in lines[: last_item_end_line + 1])


def _line_belongs_to_block(line: str, item_prefix: str) -> bool:
    """True if ``line`` is a list item or continuation under ``item_prefix``.

    Matches three shapes: the exact prefix; the rstripped prefix
    (handles short items like ``- foo``); and any line whose leading
    whitespace is at least as deep as the prefix (multi-line continuation
    of the previous item).
    """
    if not line.strip():
        return False
    if line.startswith(item_prefix) or line.startswith(item_prefix.rstrip()):
        return True
    leading = line[: len(item_prefix)]
    if leading.isspace():
        stripped_indent = len(line) - len(line.lstrip())
        return stripped_indent >= len(item_prefix)
    return False


def update_floor_entry(
    yaml_path: Path,
    office_id: str,
    floor_id: str,
    *,
    clusters: Mapping[str, Mapping[str, object]] | None = None,
    rooms: Mapping[str, Mapping[str, object]] | None = None,
) -> None:
    """Replace the ``clusters:`` and/or ``rooms:`` blocks of a floor entry.

    Used by ``office floors doctor`` (issue #54 follow-up) to auto-grow
    the YAML when the SVG has more shapes than declared. Locates the
    matching ``- id: <floor_id>`` block under ``office_id`` and replaces
    its child ``clusters:`` / ``rooms:`` subtrees textually, preserving
    everything else byte-for-byte.

    ``clusters`` is a mapping ``letter -> {"capacity": int, "type": str}``.
    ``rooms`` is a mapping ``room_id -> {"name": str, "type": str,
    "capacity": int}``. Pass ``None`` to leave that subtree unchanged.
    """
    if yaml_path.name != "offices.yaml":
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"refusing to write a non-offices.yaml file: {yaml_path}",
            remediation="pass a path whose final component is `offices.yaml`",
        )
    if not yaml_path.is_file():
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"offices.yaml not found: {yaml_path}",
            remediation="check the --data-dir or run from the repo root",
        )
    text = yaml_path.read_text(encoding="utf-8")
    parsed = _parse_offices(text, yaml_path)
    _find_office(parsed, office_id, yaml_path)  # validates existence
    lines = text.splitlines(keepends=True)
    floor_line, floor_indent = _locate_floor_in_office(lines, office_id, floor_id, yaml_path)
    nested = " " * (floor_indent + 2)
    new_text = text
    new_lines = new_text.splitlines(keepends=True)
    # Re-locate inside new_lines after each replacement (offsets shift).
    if clusters is not None:
        new_block = _format_clusters_block(dict(clusters), nested)
        new_lines = _replace_subtree(new_lines, floor_line, floor_indent, "clusters:", new_block)
        # Recompute floor_line in case clusters block size changed.
        floor_line, floor_indent = _locate_floor_in_office(
            new_lines, office_id, floor_id, yaml_path
        )
        nested = " " * (floor_indent + 2)
    if rooms is not None:
        new_block = _format_rooms_block(dict(rooms), nested)
        new_lines = _replace_subtree(new_lines, floor_line, floor_indent, "rooms:", new_block)
    yaml_path.write_text("".join(new_lines), encoding="utf-8")


def _locate_floor_in_office(
    lines: list[str], office_id: str, floor_id: str, path: Path
) -> tuple[int, int]:
    """Return ``(line_index, indent)`` for the floor's ``- id:`` line."""
    office_line, office_indent = _locate_office_block(lines, office_id, path)
    floors_line, _ = _locate_floors_key(lines, office_line, office_indent, office_id, path)
    needle = re.compile(r"^(\s*)- id:\s*" + re.escape(floor_id) + r"\s*$")
    for i in range(floors_line + 1, len(lines)):
        m = needle.match(lines[i])
        if m:
            return i, len(m.group(1))
        # If we walked past the office's floors list, the floor isn't there.
        if re.match(r"^" + " " * office_indent + r"- id:", lines[i]):
            break
    raise OfficeError(
        code=EXIT_USER_ERROR,
        message=(f"floor {floor_id!r} not found under office {office_id!r} in {path}"),
        remediation="check the floor id matches the offices.yaml entry",
    )


def _replace_subtree(
    lines: list[str],
    floor_line: int,
    floor_indent: int,
    key_name: str,
    new_block: str,
) -> list[str]:
    """Replace the ``<nested>key_name:`` block under ``floor_line``.

    The block runs from the ``key_name:`` line through every following
    line whose indent is deeper than ``floor_indent + 2`` (i.e. inside
    the floor's mapping). Stops at any line at floor-level or shallower,
    or at the next ``- id:`` of the same depth.
    """
    nested = " " * (floor_indent + 2)
    pattern = re.compile(r"^" + re.escape(nested) + re.escape(key_name) + r"\s*$")
    block_start = -1
    for i in range(floor_line + 1, len(lines)):
        if pattern.match(lines[i]):
            block_start = i
            break
        # Walked off the floor's mapping into the next sibling.
        if lines[i].startswith(" " * floor_indent + "- ") or (
            lines[i].strip() and not lines[i].startswith(nested)
        ):
            break
    if block_start < 0:
        # Key didn't exist; insert a new block at the end of the floor's mapping.
        insert_at = _find_floor_block_end(lines, floor_line, floor_indent)
        return lines[:insert_at] + [new_block] + lines[insert_at:]
    block_end = _find_subtree_end(lines, block_start, len(nested))
    return lines[:block_start] + [new_block] + lines[block_end:]


def _find_subtree_end(lines: list[str], block_start: int, key_indent: int) -> int:
    """End-line (exclusive) of a YAML key's value block."""
    for i in range(block_start + 1, len(lines)):
        line = lines[i]
        if not line.strip():
            continue
        # First line at or shallower than key_indent ends the subtree.
        leading = len(line) - len(line.lstrip())
        if leading <= key_indent:
            return i
    return len(lines)


def _find_floor_block_end(lines: list[str], floor_line: int, floor_indent: int) -> int:
    """End-line (exclusive) of a floor's mapping body."""
    nested = " " * (floor_indent + 2)
    for i in range(floor_line + 1, len(lines)):
        line = lines[i]
        if not line.strip():
            continue
        if not line.startswith(nested):
            return i
    return len(lines)


def _format_floor_block(floor: Mapping[str, object], item_indent: str = _DEFAULT_INDENT) -> str:
    """Render a floor mapping as a YAML block matching the file's indent.

    ``item_indent`` is the prefix for the leading ``- id:`` line; nested
    keys get two additional spaces. Qodo PR #57: don't hardcode the
    6-space convention — match whatever the existing `floors:` list uses.
    """
    fid = str(floor["id"]).strip()
    svg = str(floor.get("svg", f"floors/{fid}.svg")).strip()
    status = str(floor.get("status", "draft")).strip()
    nested = item_indent + "  "
    parts = [
        f"{item_indent}- id: {fid}\n",
        f"{nested}svg: {svg}\n",
        f"{nested}status: {status}\n",
    ]
    parts.append(_format_clusters_block(floor.get("clusters"), nested))
    parts.append(_format_rooms_block(floor.get("rooms"), nested))
    return "".join(parts)


def _format_clusters_block(spec: object, nested: str) -> str:
    """Render the ``clusters:`` sub-block with one line per cluster."""
    inner = nested + "  "
    if not (isinstance(spec, dict) and spec):
        return f"{nested}clusters:\n{inner}T: {{ capacity: 1, type: open-space }}\n"
    out = [f"{nested}clusters:\n"]
    for letter in sorted(spec.keys()):
        sub = spec[letter]
        if isinstance(sub, dict):
            cap = int(sub.get("capacity", 1))
            ctype = str(sub.get("type", "open-space"))
            out.append(f"{inner}{letter}: {{ capacity: {cap}, type: {ctype} }}\n")
    return "".join(out)


def _format_rooms_block(spec: object, nested: str) -> str:
    """Render the ``rooms:`` sub-block; empty dict if no rooms declared."""
    inner = nested + "  "
    if not (isinstance(spec, dict) and spec):
        return f"{nested}rooms: {{}}\n"
    out = [f"{nested}rooms:\n"]
    for room_id in sorted(spec.keys()):
        sub = spec[room_id]
        if isinstance(sub, dict):
            name = str(sub.get("name", room_id))
            rtype = str(sub.get("type", "meeting"))
            cap = int(sub.get("capacity", 0))
            out.append(
                f'{inner}"{room_id}": {{ name: "{name}", type: {rtype}, capacity: {cap} }}\n'
            )
    return "".join(out)
