"""Tests for offices.yaml loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from office_cli.cli._errors import OfficeError
from office_cli.offices import load_offices


def test_loads_fixture(data_dir: Path) -> None:
    offices = load_offices(data_dir)
    assert set(offices) == {"tlv"}
    floor = offices["tlv"].floors["tlv-floor-5"]
    assert floor.number == "5"
    assert set(floor.clusters) == {"T", "Z"}
    assert floor.clusters["T"].capacity == 6
    assert "5.18" in floor.rooms


def test_missing_yaml_raises(tmp_path: Path) -> None:
    with pytest.raises(OfficeError) as exc:
        load_offices(tmp_path)
    assert exc.value.code == 2


def test_malformed_yaml_raises(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "offices.yaml").write_text("offices: [\n", encoding="utf-8")
    with pytest.raises(OfficeError) as exc:
        load_offices(tmp_path)
    assert exc.value.code == 1


def test_duplicate_floor_id_rejected(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "offices.yaml").write_text(
        """
offices:
  - id: tlv
    name: Tel Aviv
    floors:
      - id: tlv-floor-5
        clusters: { T: { capacity: 1 } }
      - id: tlv-floor-5
        clusters: { K: { capacity: 1 } }
""".lstrip(),
        encoding="utf-8",
    )
    with pytest.raises(OfficeError) as exc:
        load_offices(tmp_path)
    assert exc.value.code == 1
    assert "duplicate floor id" in exc.value.message


def test_missing_office_id_rejected(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "offices.yaml").write_text(
        "offices:\n  - name: anonymous\n", encoding="utf-8"
    )
    with pytest.raises(OfficeError) as exc:
        load_offices(tmp_path)
    assert exc.value.code == 1
    assert "id" in exc.value.message
