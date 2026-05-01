"""Google Sheets backends for :class:`AssignmentStore` and :class:`AuditLog`.

Imports of this subpackage do not import ``gspread`` at module-load time;
the ``GspreadClient`` adapter performs a lazy import only when constructed.
That way, environments without the ``sheets`` extra installed can still
import :mod:`office_cli.seats` and use the default CSV path.
"""

from __future__ import annotations

from office_cli.seats.sheets._audit import SheetsAuditLog
from office_cli.seats.sheets._client import GspreadClient, SheetsClient
from office_cli.seats.sheets._store import SheetsStore

__all__ = ["GspreadClient", "SheetsAuditLog", "SheetsClient", "SheetsStore"]
