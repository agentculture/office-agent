"""Tests for the Drive-as-CMS hydrator.

A :class:`FakeDriveClient` plays the role of the real Drive API: an
in-memory map of folder ids → ``DriveEntry`` lists, plus a separate map
of file ids → bytes. Tests assert that ``hydrate_data_dir`` produces a
local cache that mirrors the on-disk data-dir layout, and that warm
cache hits skip downloads.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from office_cli.cli._errors import EXIT_ENV_ERROR, EXIT_USER_ERROR, OfficeError
from office_cli.drive import DriveEntry, hydrate_data_dir
from office_cli.offices import load_offices

_ROOT_ID = "root-folder-id"

_DRIVE_YAML = """\
offices:
  - id: tlv
    name: Tel Aviv
    floors:
      - id: tlv-floor-5
        svg: tlv-floor-5.svg
        clusters:
          T: {capacity: 6, type: open-space}
          Z: {capacity: 2, type: phone-room}
        rooms:
          "5.18": {name: Meeting Room 8P, type: meeting, capacity: 8}
"""

_SVG_BYTES = b"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080">
  <rect id="5-T-01" class="seat" x="0" y="0" width="40" height="60"/>
</svg>
"""


class FakeDriveClient:
    """In-memory :class:`DriveClient` for tests.

    ``folders`` maps folder id → list of immediate children; ``files``
    maps file id → bytes. Tracks call counts so cache-TTL tests can
    assert "no further downloads happened."
    """

    def __init__(
        self,
        folders: dict[str, list[DriveEntry]],
        files: dict[str, bytes],
    ) -> None:
        self.folders = folders
        self.files = files
        self.list_calls = 0
        self.download_calls = 0

    def list_folder(self, folder_id: str) -> list[DriveEntry]:
        self.list_calls += 1
        return list(self.folders.get(folder_id, []))

    def download_file(self, file_id: str) -> bytes:
        self.download_calls += 1
        if file_id not in self.files:
            raise KeyError(f"no fake bytes for file id {file_id!r}")
        return self.files[file_id]


def _build_fake(
    *,
    yaml_bytes: bytes = _DRIVE_YAML.encode("utf-8"),
    include_yaml: bool = True,
    include_office_folder: bool = True,
    include_svg: bool = True,
    office_folder_name: str = "Tel Aviv (tlv)",
) -> FakeDriveClient:
    root_children: list[DriveEntry] = []
    files: dict[str, bytes] = {}
    if include_yaml:
        root_children.append(DriveEntry(id="yaml-id", name="offices.yaml", is_folder=False))
        files["yaml-id"] = yaml_bytes
    if include_office_folder:
        root_children.append(DriveEntry(id="tlv-folder", name=office_folder_name, is_folder=True))
    folders: dict[str, list[DriveEntry]] = {_ROOT_ID: root_children}
    office_children: list[DriveEntry] = []
    if include_svg:
        office_children.append(DriveEntry(id="svg-id", name="tlv-floor-5.svg", is_folder=False))
        files["svg-id"] = _SVG_BYTES
    folders["tlv-folder"] = office_children
    return FakeDriveClient(folders, files)


def test_happy_path_hydrates_data_dir(tmp_path: Path) -> None:
    fake = _build_fake()
    cache_root = tmp_path / "cache"

    data_dir = hydrate_data_dir(
        _ROOT_ID,
        credentials_path=tmp_path / "unused.json",
        cache_root=cache_root,
        client=fake,
    )

    assert data_dir == cache_root / _ROOT_ID
    assert (data_dir / "data" / "offices.yaml").is_file()
    assert (data_dir / "floors" / "tlv-floor-5.svg").read_bytes() == _SVG_BYTES
    assert (data_dir / "seats").is_dir()

    # The cached YAML rewrites svg to the floors/<filename> form so the
    # existing _yaml.py resolver picks it up unchanged.
    cached = yaml.safe_load((data_dir / "data" / "offices.yaml").read_text())
    assert cached["offices"][0]["floors"][0]["svg"] == "floors/tlv-floor-5.svg"

    # And it threads cleanly into load_offices().
    offices = load_offices(data_dir)
    floor = offices["tlv"].floors["tlv-floor-5"]
    assert floor.svg == data_dir / "floors" / "tlv-floor-5.svg"


def test_warm_cache_skips_all_drive_calls(tmp_path: Path) -> None:
    """Within TTL the hydrator must hit Drive zero times — no downloads
    *and* no folder listings (acceptance criterion for issue #44)."""
    fake = _build_fake()
    cache_root = tmp_path / "cache"
    kwargs = {
        "credentials_path": tmp_path / "unused.json",
        "cache_root": cache_root,
        "client": fake,
        "ttl_seconds": 300,
    }

    hydrate_data_dir(_ROOT_ID, **kwargs)
    cold_downloads = fake.download_calls
    cold_lists = fake.list_calls
    assert cold_downloads == 2  # offices.yaml + one SVG
    assert cold_lists == 2  # root + one office folder

    hydrate_data_dir(_ROOT_ID, **kwargs)
    assert fake.download_calls == cold_downloads
    assert fake.list_calls == cold_lists  # warm path skipped Drive entirely


def test_zero_ttl_forces_refetch(tmp_path: Path) -> None:
    fake = _build_fake()
    cache_root = tmp_path / "cache"
    kwargs = {
        "credentials_path": tmp_path / "unused.json",
        "cache_root": cache_root,
        "client": fake,
        "ttl_seconds": 0,
    }

    hydrate_data_dir(_ROOT_ID, **kwargs)
    hydrate_data_dir(_ROOT_ID, **kwargs)
    assert fake.download_calls == 4  # two fetches each run


def test_warm_path_falls_through_when_svg_missing_from_cache(
    tmp_path: Path,
) -> None:
    """If the meta says fresh but the local SVG was deleted, the warm
    path should fall through and re-fetch via Drive instead of returning
    a broken cache."""
    fake = _build_fake()
    cache_root = tmp_path / "cache"
    kwargs = {
        "credentials_path": tmp_path / "unused.json",
        "cache_root": cache_root,
        "client": fake,
        "ttl_seconds": 300,
    }

    hydrate_data_dir(_ROOT_ID, **kwargs)
    # Simulate someone clearing the cached SVG by hand.
    (cache_root / _ROOT_ID / "floors" / "tlv-floor-5.svg").unlink()

    hydrate_data_dir(_ROOT_ID, **kwargs)
    assert (cache_root / _ROOT_ID / "floors" / "tlv-floor-5.svg").is_file()
    # The warm path bailed, so a fresh download happened.
    assert fake.download_calls == 3  # initial 2 + the refetched SVG


def test_missing_offices_yaml_raises(tmp_path: Path) -> None:
    fake = _build_fake(include_yaml=False)
    with pytest.raises(OfficeError) as exc:
        hydrate_data_dir(
            _ROOT_ID,
            credentials_path=tmp_path / "unused.json",
            cache_root=tmp_path / "cache",
            client=fake,
        )
    assert exc.value.code == EXIT_ENV_ERROR
    assert "offices.yaml" in exc.value.message


def test_missing_office_folder_raises(tmp_path: Path) -> None:
    fake = _build_fake(include_office_folder=False)
    with pytest.raises(OfficeError) as exc:
        hydrate_data_dir(
            _ROOT_ID,
            credentials_path=tmp_path / "unused.json",
            cache_root=tmp_path / "cache",
            client=fake,
        )
    assert exc.value.code == EXIT_USER_ERROR
    assert "tlv" in exc.value.message


def test_office_folder_with_different_name_format(tmp_path: Path) -> None:
    fake = _build_fake(office_folder_name="TLV Office (tlv)")
    data_dir = hydrate_data_dir(
        _ROOT_ID,
        credentials_path=tmp_path / "unused.json",
        cache_root=tmp_path / "cache",
        client=fake,
    )
    assert (data_dir / "floors" / "tlv-floor-5.svg").is_file()


def test_missing_svg_raises_with_present_listing(tmp_path: Path) -> None:
    fake = _build_fake(include_svg=False)
    fake.folders["tlv-folder"].append(
        DriveEntry(id="other", name="something-else.svg", is_folder=False)
    )
    fake.files["other"] = b"<svg/>"
    with pytest.raises(OfficeError) as exc:
        hydrate_data_dir(
            _ROOT_ID,
            credentials_path=tmp_path / "unused.json",
            cache_root=tmp_path / "cache",
            client=fake,
        )
    assert exc.value.code == EXIT_USER_ERROR
    assert "tlv-floor-5.svg" in exc.value.message
    assert "something-else.svg" in exc.value.remediation


def test_duplicate_office_folder_raises(tmp_path: Path) -> None:
    fake = _build_fake()
    fake.folders[_ROOT_ID].append(
        DriveEntry(id="dup", name="Tel Aviv duplicate (tlv)", is_folder=True)
    )
    fake.folders["dup"] = []
    with pytest.raises(OfficeError) as exc:
        hydrate_data_dir(
            _ROOT_ID,
            credentials_path=tmp_path / "unused.json",
            cache_root=tmp_path / "cache",
            client=fake,
        )
    assert exc.value.code == EXIT_USER_ERROR
    assert "multiple" in exc.value.message.lower()


def test_invalid_yaml_in_drive_raises(tmp_path: Path) -> None:
    fake = _build_fake(yaml_bytes=b"this is: not: valid: yaml: : :\n  - [")
    with pytest.raises(OfficeError) as exc:
        hydrate_data_dir(
            _ROOT_ID,
            credentials_path=tmp_path / "unused.json",
            cache_root=tmp_path / "cache",
            client=fake,
        )
    assert exc.value.code == EXIT_USER_ERROR


def test_yaml_without_offices_list_raises(tmp_path: Path) -> None:
    fake = _build_fake(yaml_bytes=b"offices: not-a-list\n")
    with pytest.raises(OfficeError) as exc:
        hydrate_data_dir(
            _ROOT_ID,
            credentials_path=tmp_path / "unused.json",
            cache_root=tmp_path / "cache",
            client=fake,
        )
    assert exc.value.code == EXIT_USER_ERROR


def test_meta_file_records_relative_paths(tmp_path: Path) -> None:
    fake = _build_fake()
    cache_root = tmp_path / "cache"
    hydrate_data_dir(
        _ROOT_ID,
        credentials_path=tmp_path / "unused.json",
        cache_root=cache_root,
        client=fake,
    )
    meta = json.loads((cache_root / _ROOT_ID / ".meta" / "fetched-at.json").read_text())
    assert set(meta.keys()) == {"data/offices.yaml", "floors/tlv-floor-5.svg"}


def test_empty_root_id_raises(tmp_path: Path) -> None:
    fake = _build_fake()
    with pytest.raises(OfficeError) as exc:
        hydrate_data_dir(
            "",
            credentials_path=tmp_path / "unused.json",
            cache_root=tmp_path / "cache",
            client=fake,
        )
    assert exc.value.code == EXIT_ENV_ERROR


def test_duplicate_svg_filename_raises(tmp_path: Path) -> None:
    """Drive permits same-name siblings; the hydrator must not pick one
    arbitrarily."""
    fake = _build_fake()
    fake.folders["tlv-folder"].append(
        DriveEntry(id="svg-id-2", name="tlv-floor-5.svg", is_folder=False)
    )
    fake.files["svg-id-2"] = b"<svg/>"
    with pytest.raises(OfficeError) as exc:
        hydrate_data_dir(
            _ROOT_ID,
            credentials_path=tmp_path / "unused.json",
            cache_root=tmp_path / "cache",
            client=fake,
        )
    assert exc.value.code == EXIT_USER_ERROR
    assert "multiple files" in exc.value.message.lower()
    assert "tlv-floor-5.svg" in exc.value.message


def test_non_mapping_office_entry_raises(tmp_path: Path) -> None:
    """Non-dict office entries must raise immediately — the hydrator must
    not write a half-baked YAML to the cache that fails later in
    load_offices()."""
    bad_yaml = b"offices:\n  - just a string\n"
    fake = _build_fake(yaml_bytes=bad_yaml)
    with pytest.raises(OfficeError) as exc:
        hydrate_data_dir(
            _ROOT_ID,
            credentials_path=tmp_path / "unused.json",
            cache_root=tmp_path / "cache",
            client=fake,
        )
    assert exc.value.code == EXIT_USER_ERROR
    assert "not a mapping" in exc.value.message


def test_non_mapping_floor_entry_raises(tmp_path: Path) -> None:
    bad_yaml = b"""\
offices:
  - id: tlv
    name: Tel Aviv
    floors:
      - just a string
"""
    fake = _build_fake(yaml_bytes=bad_yaml)
    with pytest.raises(OfficeError) as exc:
        hydrate_data_dir(
            _ROOT_ID,
            credentials_path=tmp_path / "unused.json",
            cache_root=tmp_path / "cache",
            client=fake,
        )
    assert exc.value.code == EXIT_USER_ERROR
    assert "not a mapping" in exc.value.message
    assert "tlv" in exc.value.message


def test_office_missing_id_raises(tmp_path: Path) -> None:
    bad_yaml = b"offices:\n  - name: nameless\n"
    fake = _build_fake(yaml_bytes=bad_yaml)
    with pytest.raises(OfficeError) as exc:
        hydrate_data_dir(
            _ROOT_ID,
            credentials_path=tmp_path / "unused.json",
            cache_root=tmp_path / "cache",
            client=fake,
        )
    assert exc.value.code == EXIT_USER_ERROR
    assert "missing an `id`" in exc.value.message
