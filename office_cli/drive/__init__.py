"""Google Drive backend: load ``offices.yaml`` + floor SVGs from Drive.

When ``OFFICE_DRIVE_ROOT`` is set, :func:`hydrate_data_dir` pulls the
topology file and every declared SVG into a local cache that mirrors
the on-disk data-dir layout. The rest of the codebase keeps reading
local paths and is none the wiser.
"""

from __future__ import annotations

from office_cli.drive._cache import CacheMeta
from office_cli.drive._client import DriveClient, DriveEntry, GoogleDriveClient
from office_cli.drive._hydrate import hydrate_data_dir

__all__ = [
    "CacheMeta",
    "DriveClient",
    "DriveEntry",
    "GoogleDriveClient",
    "hydrate_data_dir",
]
