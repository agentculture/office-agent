"""Tests for the Drive client construction error paths.

The actual Google API surface is exercised through ``FakeDriveClient``
in :mod:`tests.test_drive_hydrate`. Here we only assert that the
production :class:`GoogleDriveClient` raises the right error when its
prerequisites aren't met — missing credential file is the only path
we can exercise without standing up a real Drive.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from office_cli.cli._errors import EXIT_ENV_ERROR, OfficeError
from office_cli.drive import GoogleDriveClient


def test_missing_service_account_file_raises(tmp_path: Path) -> None:
    bogus = tmp_path / "no-such-sa.json"
    with pytest.raises(OfficeError) as exc:
        GoogleDriveClient(bogus)
    assert exc.value.code == EXIT_ENV_ERROR
    assert "service-account" in exc.value.message
    assert "OFFICE_DRIVE_CREDENTIALS" in exc.value.remediation


def test_drive_entry_immutable() -> None:
    from office_cli.drive import DriveEntry

    entry = DriveEntry(id="x", name="y", is_folder=False)
    with pytest.raises(Exception):
        entry.name = "changed"  # type: ignore[misc]
