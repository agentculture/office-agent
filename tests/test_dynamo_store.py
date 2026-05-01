"""Tests for the DynamoDB-backed AssignmentStore.

A ``FakeDynamoClient`` plays the role of boto3; no real AWS creds are
needed. Cache-TTL behavior is exercised with an injected clock,
mirroring the Sheets test pattern.
"""

from __future__ import annotations

from itertools import count

from office_cli.seats import Assignment
from office_cli.seats.dynamo import DynamoStore


class FakeDynamoClient:
    """Minimal in-memory DynamoDB shim for store / audit tests."""

    def __init__(self) -> None:
        self.tables: dict[str, dict[tuple, dict]] = {}
        self.scan_calls = 0

    def _key(self, table: str, item: dict) -> tuple[str, str]:
        # Always return a (pk, sk) pair. Assignments use SK="" since
        # they're keyed on seat_id alone; audit tables key on
        # (seat_id, timestamp). Keeping the shape uniform avoids the
        # variable-length tuple Sonar S8495 flags.
        is_audit = "audit" in table
        sk = item.get("timestamp", "") if is_audit else ""
        return (item.get("seat_id", ""), sk)

    def scan_all(self, table: str) -> list[dict]:
        self.scan_calls += 1
        return [dict(v) for v in self.tables.get(table, {}).values()]

    def put_item(self, table: str, item: dict) -> None:
        self.tables.setdefault(table, {})[self._key(table, item)] = dict(item)

    def batch_put(self, table: str, items: list[dict]) -> None:
        for item in items:
            self.put_item(table, item)

    def query_by_pk(self, table: str, pk_name: str, pk_value: str) -> list[dict]:
        return [dict(v) for v in self.tables.get(table, {}).values() if v.get(pk_name) == pk_value]


def _store(client: FakeDynamoClient | None = None, ttl: int = 0) -> DynamoStore:
    return DynamoStore(
        client or FakeDynamoClient(), table="office-assignments", cache_ttl_seconds=ttl
    )


def test_round_trip() -> None:
    client = FakeDynamoClient()
    store = DynamoStore(client, table="office-assignments", cache_ttl_seconds=0)
    a = Assignment(
        seat_id="5-T-01",
        floor="tlv-floor-5",
        employee_email="alice@example.com",
        last_updated="2026-05-01T00:00:01Z",
        hidden=True,
        notes="ergonomic",
    )
    store.upsert(a)
    rows = store.list()
    assert len(rows) == 1
    assert rows[0].seat_id == "5-T-01"
    assert rows[0].employee_email == "alice@example.com"
    assert rows[0].hidden is True


def test_upsert_replaces_existing() -> None:
    client = FakeDynamoClient()
    store = DynamoStore(client, table="office-assignments", cache_ttl_seconds=0)
    store.upsert(Assignment(seat_id="5-T-01", floor="tlv-floor-5", employee_email="a@x"))
    store.upsert(Assignment(seat_id="5-T-01", floor="tlv-floor-5", employee_email="b@x"))
    rows = store.list()
    assert len(rows) == 1
    assert rows[0].employee_email == "b@x"


def test_by_email_filter() -> None:
    client = FakeDynamoClient()
    store = DynamoStore(client, table="office-assignments", cache_ttl_seconds=0)
    store.upsert_many(
        [
            Assignment(seat_id="5-T-01", floor="tlv-floor-5", employee_email="a@x"),
            Assignment(seat_id="5-T-02", floor="tlv-floor-5", employee_email="b@x"),
        ]
    )
    found = store.by_email("b@x")
    assert found is not None
    assert found.seat_id == "5-T-02"
    assert store.by_email("ghost@x") is None
    assert store.by_email("") is None


def test_cache_ttl_honored() -> None:
    counter = count(0, 1)

    def clock() -> float:
        return float(next(counter))

    client = FakeDynamoClient()
    store = DynamoStore(
        client,
        table="office-assignments",
        cache_ttl_seconds=10,
        clock=clock,
    )
    store.upsert(Assignment(seat_id="5-T-01", floor="tlv-floor-5", employee_email="a@x"))
    base_calls = client.scan_calls
    # First list — populates cache (write invalidated above).
    store.list()
    after_first = client.scan_calls
    # Second list within the TTL — must not hit the underlying client again.
    store.list()
    assert client.scan_calls == after_first
    # The first list went to the wire; subsequent reads stayed cached.
    assert after_first == base_calls + 1


def test_upsert_invalidates_cache() -> None:
    client = FakeDynamoClient()
    store = DynamoStore(client, table="office-assignments", cache_ttl_seconds=999)
    store.upsert(Assignment(seat_id="5-T-01", floor="tlv-floor-5", employee_email="a@x"))
    store.list()  # populate cache
    cached_scans = client.scan_calls
    store.upsert(Assignment(seat_id="5-T-02", floor="tlv-floor-5", employee_email="b@x"))
    # Cache invalidated → next list goes back to the wire.
    rows = store.list()
    assert client.scan_calls == cached_scans + 1
    assert {r.seat_id for r in rows} == {"5-T-01", "5-T-02"}


def test_list_sorted_by_floor_then_seat() -> None:
    client = FakeDynamoClient()
    store = DynamoStore(client, table="office-assignments", cache_ttl_seconds=0)
    store.upsert_many(
        [
            Assignment(seat_id="5-T-02", floor="tlv-floor-5"),
            Assignment(seat_id="5-T-01", floor="tlv-floor-5"),
            Assignment(seat_id="2-A-01", floor="ber-floor-2"),
        ]
    )
    ids = [r.seat_id for r in store.list()]
    assert ids == ["2-A-01", "5-T-01", "5-T-02"]
