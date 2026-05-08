"""Tests for ``append_floor_entry`` (the textual YAML splice)."""

from __future__ import annotations

from pathlib import Path

import pytest

from office_cli.cli._errors import EXIT_USER_ERROR, OfficeError
from office_cli.offices import append_floor_entry, load_offices, update_floor_entry

_TWO_OFFICE_YAML = """\
# This top-level comment must survive any append.

# Stage 7 — SSO + roles. Comment block to preserve.

offices:
  - id: tlv
    name: "Tel Aviv"
    address: "Tel Aviv, Israel"
    floors:
      - id: tlv-floor-5
        svg: floors/tlv-floor-5.svg
        status: active
        clusters:
          T: { capacity: 6, type: open-space }
        rooms:
          "5.18": { name: "Conf 5.18", type: meeting, capacity: 8 }
  - id: nyc
    name: "New York"
    floors:
      - id: nyc-floor-12
        svg: floors/nyc-floor-12.svg
        status: active
        clusters:
          A: { capacity: 4, type: open-space }
        rooms: {}
"""


def _write(tmp_path: Path) -> Path:
    yaml_path = tmp_path / "data" / "offices.yaml"
    yaml_path.parent.mkdir(parents=True)
    yaml_path.write_text(_TWO_OFFICE_YAML, encoding="utf-8")
    return yaml_path


def test_append_appends_under_correct_office(tmp_path: Path) -> None:
    yaml_path = _write(tmp_path)
    append_floor_entry(
        yaml_path,
        "tlv",
        {
            "id": "tlv-floor-3",
            "svg": "floors/tlv-floor-3.svg",
            "clusters": {"T": {"capacity": 6, "type": "open-space"}},
            "rooms": {},
        },
    )
    offices = load_offices(tmp_path)
    floors = offices["tlv"].floors
    assert "tlv-floor-3" in floors
    assert "tlv-floor-5" in floors
    assert floors["tlv-floor-3"].status == "draft"
    assert floors["tlv-floor-3"].clusters["T"].capacity == 6
    # NYC untouched.
    assert list(offices["nyc"].floors) == ["nyc-floor-12"]


def test_append_preserves_top_level_comments(tmp_path: Path) -> None:
    yaml_path = _write(tmp_path)
    append_floor_entry(
        yaml_path,
        "tlv",
        {"id": "tlv-floor-7", "svg": "floors/tlv-floor-7.svg"},
    )
    text = yaml_path.read_text(encoding="utf-8")
    assert "# This top-level comment must survive any append." in text
    assert "# Stage 7 — SSO + roles." in text


def test_append_preserves_existing_floor_block(tmp_path: Path) -> None:
    """All lines from the original file must survive (they may be
    bisected by the new entry, but each line still appears in order)."""
    yaml_path = _write(tmp_path)
    before = yaml_path.read_text(encoding="utf-8")
    append_floor_entry(
        yaml_path,
        "tlv",
        {"id": "tlv-floor-7", "svg": "floors/tlv-floor-7.svg"},
    )
    after = yaml_path.read_text(encoding="utf-8")
    # Every original line still appears (in original order — no reorder).
    for line in before.splitlines():
        assert line in after
    # New entry landed.
    assert "tlv-floor-7" in after
    # And the new entry is under the tlv block, not nyc — it appears
    # before `- id: nyc` in the file.
    assert after.index("tlv-floor-7") < after.index("- id: nyc")


def test_append_refuses_duplicate_floor_id(tmp_path: Path) -> None:
    yaml_path = _write(tmp_path)
    with pytest.raises(OfficeError) as exc:
        append_floor_entry(
            yaml_path,
            "tlv",
            {"id": "tlv-floor-5", "svg": "floors/tlv-floor-5.svg"},
        )
    assert exc.value.code == EXIT_USER_ERROR
    assert "already declared" in exc.value.message


def test_append_refuses_unknown_office(tmp_path: Path) -> None:
    yaml_path = _write(tmp_path)
    with pytest.raises(OfficeError) as exc:
        append_floor_entry(
            yaml_path,
            "no-such",
            {"id": "no-floor", "svg": "floors/no.svg"},
        )
    assert exc.value.code == EXIT_USER_ERROR
    assert "unknown office" in exc.value.message


def test_append_refuses_missing_id(tmp_path: Path) -> None:
    yaml_path = _write(tmp_path)
    with pytest.raises(OfficeError) as exc:
        append_floor_entry(yaml_path, "tlv", {"svg": "floors/x.svg"})
    assert "missing `id`" in exc.value.message


def test_append_refuses_missing_file(tmp_path: Path) -> None:
    bogus = tmp_path / "data" / "offices.yaml"
    with pytest.raises(OfficeError) as exc:
        append_floor_entry(bogus, "tlv", {"id": "x", "svg": "y.svg"})
    assert "not found" in exc.value.message


def test_append_refuses_non_offices_yaml_filename(tmp_path: Path) -> None:
    """Sonar PR #57 review (S2083): the path must end with
    `offices.yaml`. Defends against the writer being pointed at a
    system file via a mis-set --data-dir."""
    danger = tmp_path / "passwd"
    danger.write_text("not yaml", encoding="utf-8")
    with pytest.raises(OfficeError) as exc:
        append_floor_entry(danger, "tlv", {"id": "x", "svg": "y.svg"})
    assert "non-offices.yaml" in exc.value.message
    # File untouched.
    assert danger.read_text(encoding="utf-8") == "not yaml"


def test_append_refuses_malformed_yaml(tmp_path: Path) -> None:
    yaml_path = tmp_path / "data" / "offices.yaml"
    yaml_path.parent.mkdir(parents=True)
    yaml_path.write_text("offices: not: valid: yaml: : :\n  - [\n", encoding="utf-8")
    with pytest.raises(OfficeError) as exc:
        append_floor_entry(yaml_path, "tlv", {"id": "x", "svg": "y.svg"})
    assert "not valid YAML" in exc.value.message


def test_append_inherited_clusters_and_rooms(tmp_path: Path) -> None:
    """A new floor may carry the full cluster + room spec inherited
    from a `--copy-from` source."""
    yaml_path = _write(tmp_path)
    append_floor_entry(
        yaml_path,
        "tlv",
        {
            "id": "tlv-floor-3",
            "svg": "floors/tlv-floor-3.svg",
            "clusters": {
                "T": {"capacity": 6, "type": "open-space"},
                "Z": {"capacity": 2, "type": "phone-room"},
            },
            "rooms": {
                "3.10": {"name": "Conf 3.10", "type": "meeting", "capacity": 8},
            },
        },
    )
    offices = load_offices(tmp_path)
    floor = offices["tlv"].floors["tlv-floor-3"]
    assert sorted(floor.clusters.keys()) == ["T", "Z"]
    assert floor.clusters["Z"].capacity == 2
    assert floor.rooms["3.10"].name == "Conf 3.10"


def test_append_drops_into_empty_floors_list(tmp_path: Path) -> None:
    """If an office declares `floors: []`, the append still works."""
    yaml_path = tmp_path / "data" / "offices.yaml"
    yaml_path.parent.mkdir(parents=True)
    yaml_path.write_text(
        'offices:\n  - id: tlv\n    name: "Tel Aviv"\n    floors:\n',
        encoding="utf-8",
    )
    append_floor_entry(
        yaml_path,
        "tlv",
        {"id": "tlv-floor-1", "svg": "floors/tlv-floor-1.svg"},
    )
    offices = load_offices(tmp_path)
    assert "tlv-floor-1" in offices["tlv"].floors


def test_append_matches_existing_indentation(tmp_path: Path) -> None:
    """Qodo PR #57 review: writer must use the file's existing list-item
    indentation, not a hardcoded 6 spaces."""
    yaml_path = tmp_path / "data" / "offices.yaml"
    yaml_path.parent.mkdir(parents=True)
    # 2-space-deeper indentation (8 spaces for floor items).
    yaml_path.write_text(
        "offices:\n"
        "    - id: tlv\n"
        '      name: "Tel Aviv"\n'
        "      floors:\n"
        "        - id: tlv-floor-5\n"
        "          svg: floors/tlv-floor-5.svg\n"
        "          status: active\n"
        "          clusters:\n"
        "            T: { capacity: 1, type: open-space }\n"
        "          rooms: {}\n",
        encoding="utf-8",
    )
    append_floor_entry(
        yaml_path,
        "tlv",
        {"id": "tlv-floor-3", "svg": "floors/tlv-floor-3.svg"},
    )
    text = yaml_path.read_text(encoding="utf-8")
    # The new entry's `- id:` line must have the same 8-space prefix as
    # the existing one.
    assert "        - id: tlv-floor-3" in text
    # And load_offices must still succeed (well-formed YAML).
    offices = load_offices(tmp_path)
    assert "tlv-floor-3" in offices["tlv"].floors


def test_update_floor_entry_replaces_clusters(tmp_path: Path) -> None:
    """Doctor's auto-grow path: bump T's capacity from 6 to 21 in-place."""
    yaml_path = _write(tmp_path)
    update_floor_entry(
        yaml_path,
        "tlv",
        "tlv-floor-5",
        clusters={"T": {"capacity": 21, "type": "open-space"}},
    )
    offices = load_offices(tmp_path)
    floor = offices["tlv"].floors["tlv-floor-5"]
    assert floor.clusters["T"].capacity == 21
    # Other floors untouched.
    assert offices["nyc"].floors["nyc-floor-12"].clusters["A"].capacity == 4


def test_update_floor_entry_replaces_rooms(tmp_path: Path) -> None:
    """Replace the rooms block with a new sequential list."""
    yaml_path = _write(tmp_path)
    new_rooms = {
        f"5.{n}": {"name": f"Room 5.{n}", "type": "meeting", "capacity": 4} for n in range(18, 32)
    }
    update_floor_entry(yaml_path, "tlv", "tlv-floor-5", rooms=new_rooms)
    offices = load_offices(tmp_path)
    floor = offices["tlv"].floors["tlv-floor-5"]
    assert sorted(floor.rooms.keys()) == [f"5.{n}" for n in range(18, 32)]


def test_update_floor_entry_preserves_top_level_comments(tmp_path: Path) -> None:
    yaml_path = _write(tmp_path)
    update_floor_entry(
        yaml_path,
        "tlv",
        "tlv-floor-5",
        clusters={"T": {"capacity": 21, "type": "open-space"}},
    )
    text = yaml_path.read_text(encoding="utf-8")
    assert "# This top-level comment must survive any append." in text
    assert "# Stage 7 — SSO + roles." in text


def test_update_floor_entry_replaces_both_clusters_and_rooms(tmp_path: Path) -> None:
    yaml_path = _write(tmp_path)
    update_floor_entry(
        yaml_path,
        "tlv",
        "tlv-floor-5",
        clusters={
            "T": {"capacity": 21, "type": "open-space"},
            "Z": {"capacity": 0, "type": "phone-room"},
        },
        rooms={
            f"5.{n}": {"name": f"Room 5.{n}", "type": "meeting", "capacity": 4}
            for n in range(18, 25)
        },
    )
    offices = load_offices(tmp_path)
    floor = offices["tlv"].floors["tlv-floor-5"]
    assert floor.clusters["T"].capacity == 21
    assert floor.clusters["Z"].capacity == 0
    assert len(floor.rooms) == 7


def test_update_floor_entry_refuses_unknown_floor(tmp_path: Path) -> None:
    yaml_path = _write(tmp_path)
    with pytest.raises(OfficeError) as exc:
        update_floor_entry(
            yaml_path,
            "tlv",
            "no-such-floor",
            clusters={"T": {"capacity": 6, "type": "open-space"}},
        )
    assert exc.value.code == EXIT_USER_ERROR
    assert "not found" in exc.value.message


def test_update_floor_entry_refuses_unknown_office(tmp_path: Path) -> None:
    yaml_path = _write(tmp_path)
    with pytest.raises(OfficeError) as exc:
        update_floor_entry(
            yaml_path,
            "no-such-office",
            "tlv-floor-5",
            clusters={"T": {"capacity": 6, "type": "open-space"}},
        )
    assert exc.value.code == EXIT_USER_ERROR
    assert "unknown office" in exc.value.message
