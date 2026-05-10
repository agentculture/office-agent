"""Load ``data/offices.yaml`` into the typed model."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from office_cli.cli._errors import EXIT_ENV_ERROR, EXIT_USER_ERROR, OfficeError
from office_cli.offices._models import Cluster, Floor, Office, Room


def load_offices(data_dir: Path) -> dict[str, Office]:
    """Parse ``<data_dir>/data/offices.yaml`` → ``{office_id: Office}``."""
    yaml_path = data_dir / "data" / "offices.yaml"
    if not yaml_path.is_file():
        raise OfficeError(
            code=EXIT_ENV_ERROR,
            message=f"offices.yaml not found at {yaml_path}",
            remediation=(
                "bootstrap from the demo: cp data/offices.demo.yaml "
                "data/offices.yaml — or set OFFICE_DATA_DIR / pass --data-dir"
            ),
        )
    with yaml_path.open("r", encoding="utf-8") as f:
        try:
            raw = yaml.safe_load(f) or {}
        except yaml.YAMLError as err:
            raise OfficeError(
                code=EXIT_USER_ERROR,
                message=f"offices.yaml is not valid YAML: {err}",
                remediation="fix the YAML syntax and rerun",
            ) from err

    offices_raw = raw.get("offices")
    if not isinstance(offices_raw, list):
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message="offices.yaml must contain a top-level `offices:` list",
            remediation="see data/offices.demo.yaml in the office-agent repo for the expected shape",
        )

    offices: dict[str, Office] = {}
    floors_dir = data_dir / "floors"
    for entry in offices_raw:
        office = _parse_office(entry, floors_dir)
        if office.id in offices:
            raise OfficeError(
                code=EXIT_USER_ERROR,
                message=f"duplicate office id: {office.id}",
                remediation="office ids must be globally unique in offices.yaml",
            )
        offices[office.id] = office
    return offices


def _require(d: dict[str, Any], key: str, ctx: str) -> Any:
    if key not in d:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"missing required field `{key}` in {ctx}",
            remediation=f"add `{key}: ...` to the {ctx} entry",
        )
    return d[key]


def _parse_office(entry: Any, floors_dir: Path) -> Office:
    if not isinstance(entry, dict):
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message="each office entry must be a mapping",
            remediation="see data/offices.yaml for the expected shape",
        )
    oid = str(_require(entry, "id", "office"))
    name = str(_require(entry, "name", f"office {oid}"))
    address = str(entry.get("address", ""))
    floors_raw = entry.get("floors", []) or []
    floors: dict[str, Floor] = {}
    for f in floors_raw:
        floor = _parse_floor(f, floors_dir, oid)
        if floor.id in floors:
            raise OfficeError(
                code=EXIT_USER_ERROR,
                message=f"duplicate floor id under office `{oid}`: {floor.id}",
                remediation="floor ids must be unique within an office in offices.yaml",
            )
        floors[floor.id] = floor
    return Office(id=oid, name=name, address=address, floors=floors)


def _parse_floor(entry: Any, floors_dir: Path, office_id: str) -> Floor:
    if not isinstance(entry, dict):
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"each floor entry under office `{office_id}` must be a mapping",
            remediation="see data/offices.yaml for the expected shape",
        )
    fid = str(_require(entry, "id", f"floor under office {office_id}"))
    svg_field = entry.get("svg", f"floors/{fid}.svg")
    svg_path = Path(svg_field)
    if not svg_path.is_absolute():
        # Resolve relative to the data_dir (parent of `floors/`).
        svg_path = floors_dir.parent / svg_path
    clusters: dict[str, Cluster] = {}
    for letter, cdata in (entry.get("clusters") or {}).items():
        cdata = cdata or {}
        clusters[letter] = Cluster(
            letter=letter,
            capacity=int(cdata.get("capacity", 0)),
            type=str(cdata.get("type", "open-space")),
        )
    rooms: dict[str, Room] = {}
    for rid, rdata in (entry.get("rooms") or {}).items():
        rdata = rdata or {}
        rooms[rid] = Room(
            id=str(rid),
            name=str(rdata.get("name", rid)),
            type=str(rdata.get("type", "meeting")),
            capacity=int(rdata.get("capacity", 0)),
        )
    status = str(entry.get("status", "active"))
    return Floor(id=fid, svg=svg_path, clusters=clusters, rooms=rooms, status=status)
