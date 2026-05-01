"""Thin shim over the Google Sheets API.

The :class:`SheetsClient` Protocol exposes only the three operations the
store and audit log need (read / replace / append). The store is unit-
tested against a ``FakeSheetsClient`` so the test suite never needs real
credentials. :class:`GspreadClient` is the production implementation —
import is deferred to construction so the parent package can be imported
without the ``[sheets]`` extra installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from office_cli.cli._errors import EXIT_ENV_ERROR, OfficeError


class SheetsClient(Protocol):
    def read_rows(self, worksheet: str) -> list[list[str]]:
        """Return every cell value in ``worksheet`` as ``[[row], [row], ...]``."""

    def replace_rows(self, worksheet: str, rows: list[list[str]]) -> None:
        """Atomically replace the contents of ``worksheet`` with ``rows``."""

    def append_rows(self, worksheet: str, rows: list[list[str]]) -> None:
        """Append ``rows`` to the bottom of ``worksheet``."""


class GspreadClient:
    """Production :class:`SheetsClient` implementation backed by ``gspread``."""

    def __init__(self, spreadsheet_id: str, service_account_path: Path) -> None:
        try:
            import gspread  # noqa: F401 — runtime check
        except ImportError as err:
            raise OfficeError(
                code=EXIT_ENV_ERROR,
                message="gspread is not installed",
                remediation="install the sheets extra: pip install office-cli[sheets]",
            ) from err
        if not service_account_path.is_file():
            raise OfficeError(
                code=EXIT_ENV_ERROR,
                message=f"service-account JSON not found: {service_account_path}",
                remediation=(
                    "point OFFICE_SHEETS_SA / storage.sheets.service_account at a real file"
                ),
            )
        self._spreadsheet_id = spreadsheet_id
        self._service_account_path = service_account_path
        self._spreadsheet = None

    def _open(self):
        if self._spreadsheet is None:
            import gspread

            gc = gspread.service_account(filename=str(self._service_account_path))
            self._spreadsheet = gc.open_by_key(self._spreadsheet_id)
        return self._spreadsheet

    def _worksheet(self, name: str):
        sh = self._open()
        try:
            return sh.worksheet(name)
        except Exception:  # gspread.WorksheetNotFound or transport
            return sh.add_worksheet(title=name, rows=1, cols=10)

    def read_rows(self, worksheet: str) -> list[list[str]]:
        ws = self._worksheet(worksheet)
        return ws.get_all_values()

    def replace_rows(self, worksheet: str, rows: list[list[str]]) -> None:
        ws = self._worksheet(worksheet)
        ws.clear()
        if rows:
            ws.update(values=rows, range_name=f"A1:{_col_letter(len(rows[0]))}{len(rows)}")

    def append_rows(self, worksheet: str, rows: list[list[str]]) -> None:
        if not rows:
            return
        ws = self._worksheet(worksheet)
        ws.append_rows(rows, value_input_option="USER_ENTERED")


def _col_letter(n: int) -> str:
    """1 → A, 26 → Z, 27 → AA. Used for range bounds."""
    out = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out = chr(ord("A") + rem) + out
    return out
