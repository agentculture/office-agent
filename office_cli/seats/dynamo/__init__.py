"""DynamoDB backends for :class:`AssignmentStore` and :class:`AuditLog`.

Imports of this subpackage do not import ``boto3`` at module-load time;
the ``Boto3DynamoClient`` adapter performs a lazy import only when
constructed. That way, environments without the ``dynamo`` extra
installed can still import :mod:`office_cli.seats` and use the default
CSV path or the Sheets backend.
"""

from __future__ import annotations

from office_cli.seats.dynamo._audit import DynamoAuditLog
from office_cli.seats.dynamo._client import Boto3DynamoClient, DynamoClient
from office_cli.seats.dynamo._store import DynamoStore

__all__ = ["Boto3DynamoClient", "DynamoAuditLog", "DynamoClient", "DynamoStore"]
