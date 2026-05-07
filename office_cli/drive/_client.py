"""Thin shim over the Google Drive v3 API.

The :class:`DriveClient` Protocol exposes only what the hydrator needs:
list a folder's immediate children and download a file's bytes. The
hydrator is unit-tested against a ``FakeDriveClient`` so the suite
never needs real credentials. :class:`GoogleDriveClient` is the
production implementation; the ``googleapiclient`` / ``google-auth``
imports are deferred to first use so the parent package can be
imported without the ``[drive]`` extra installed.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from office_cli.cli._errors import EXIT_ENV_ERROR, OfficeError

_DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
_FOLDER_MIME = "application/vnd.google-apps.folder"
_PAGE_SIZE = 100


@dataclass(frozen=True)
class DriveEntry:
    """One immediate child of a Drive folder."""

    id: str
    name: str
    is_folder: bool


class DriveClient(Protocol):
    def list_folder(self, folder_id: str) -> list[DriveEntry]:
        """Return ``folder_id``'s immediate children (files + subfolders)."""

    def download_file(self, file_id: str) -> bytes:
        """Return the raw bytes of ``file_id``."""


class GoogleDriveClient:
    """Production :class:`DriveClient` backed by ``google-api-python-client``."""

    def __init__(self, service_account_path: Path) -> None:
        try:
            import google.oauth2.service_account  # noqa: F401 — runtime check
            import googleapiclient.discovery  # noqa: F401 — runtime check
        except ImportError as err:
            raise OfficeError(
                code=EXIT_ENV_ERROR,
                message="google-api-python-client is not installed",
                remediation="install the drive extra: pip install office-cli[drive]",
            ) from err
        if not service_account_path.is_file():
            raise OfficeError(
                code=EXIT_ENV_ERROR,
                message=f"Drive service-account JSON not found: {service_account_path}",
                remediation=(
                    "set OFFICE_DRIVE_CREDENTIALS to a real file, or "
                    "place the SA JSON at data/sheets-service-account.json"
                ),
            )
        self._service_account_path = service_account_path
        self._service = None

    def _connect(self):
        if self._service is None:
            from google.oauth2.service_account import Credentials
            from googleapiclient.discovery import build

            creds = Credentials.from_service_account_file(
                str(self._service_account_path),
                scopes=[_DRIVE_READONLY_SCOPE],
            )
            self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return self._service

    def list_folder(self, folder_id: str) -> list[DriveEntry]:
        svc = self._connect()
        out: list[DriveEntry] = []
        page_token: str | None = None
        while True:
            resp = (
                svc.files()
                .list(
                    q=f"'{folder_id}' in parents and trashed = false",
                    fields="nextPageToken, files(id, name, mimeType)",
                    pageSize=_PAGE_SIZE,
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
            for entry in resp.get("files", []):
                out.append(
                    DriveEntry(
                        id=entry["id"],
                        name=entry["name"],
                        is_folder=entry.get("mimeType") == _FOLDER_MIME,
                    )
                )
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return out

    def download_file(self, file_id: str) -> bytes:
        from googleapiclient.http import MediaIoBaseDownload

        svc = self._connect()
        request = svc.files().get_media(fileId=file_id, supportsAllDrives=True)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue()
