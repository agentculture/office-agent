"""Thin shim over the AWS DynamoDB API.

The :class:`DynamoClient` Protocol exposes only the four operations the
store and audit log need (``scan_all`` / ``put_item`` / ``batch_put`` /
``query_by_pk``). The store is unit-tested against a ``FakeDynamoClient``
so the test suite never needs real AWS credentials.
:class:`Boto3DynamoClient` is the production implementation — import is
deferred to construction so the parent package can be imported without
the ``[dynamo]`` extra installed.
"""

from __future__ import annotations

from typing import Protocol

from office_cli.cli._errors import EXIT_ENV_ERROR, OfficeError


class DynamoClient(Protocol):
    def scan_all(self, table: str) -> list[dict]:
        """Return every item in ``table`` as a list of attribute dicts."""

    def put_item(self, table: str, item: dict) -> None:
        """Insert or replace a single ``item`` keyed by its PK (+ SK)."""

    def batch_put(self, table: str, items: list[dict]) -> None:
        """Best-effort batched put for ``items``. Idempotent by primary key."""

    def query_by_pk(self, table: str, pk_name: str, pk_value: str) -> list[dict]:
        """Return items matching a partition-key equality, ordered by sort key."""


class Boto3DynamoClient:
    """Production :class:`DynamoClient` backed by ``boto3.resource("dynamodb")``."""

    def __init__(self, region: str) -> None:
        try:
            import boto3  # noqa: F401 — runtime check
        except ImportError as err:
            raise OfficeError(
                code=EXIT_ENV_ERROR,
                message="boto3 is not installed",
                remediation="install the dynamo extra: pip install office-cli[dynamo]",
            ) from err
        self._region = region
        self._resource = None

    def _ddb(self):
        if self._resource is None:
            import boto3

            self._resource = boto3.resource("dynamodb", region_name=self._region)
        return self._resource

    def scan_all(self, table: str) -> list[dict]:
        tbl = self._ddb().Table(table)
        items: list[dict] = []
        kwargs: dict = {}
        while True:
            resp = tbl.scan(**kwargs)
            items.extend(resp.get("Items", []))
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last
        return items

    def put_item(self, table: str, item: dict) -> None:
        self._ddb().Table(table).put_item(Item=item)

    def batch_put(self, table: str, items: list[dict]) -> None:
        if not items:
            return
        tbl = self._ddb().Table(table)
        with tbl.batch_writer() as bw:
            for item in items:
                bw.put_item(Item=item)

    def query_by_pk(self, table: str, pk_name: str, pk_value: str) -> list[dict]:
        from boto3.dynamodb.conditions import Key

        tbl = self._ddb().Table(table)
        items: list[dict] = []
        kwargs: dict = {"KeyConditionExpression": Key(pk_name).eq(pk_value)}
        while True:
            resp = tbl.query(**kwargs)
            items.extend(resp.get("Items", []))
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last
        return items
