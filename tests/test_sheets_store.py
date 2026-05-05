"""Tests for the Sheets-backed AssignmentStore + AuditLog.

A ``FakeSheetsClient`` plays the role of gspread; no real creds are
needed. Cache-TTL behavior is exercised with an injected clock.
"""

from __future__ import annotations

from itertools import count

import pytest

from office_cli.seats import Assignment, AuditEntry
from office_cli.seats._audit import FIELDNAMES
from office_cli.seats.sheets import SheetsAuditLog, SheetsStore


class FakeSheetsClient:
    def __init__(self) -> None:
        self.tabs: dict[str, list[list[str]]] = {}
        self.read_calls = 0

    def read_rows(self, worksheet: str) -> list[list[str]]:
        self.read_calls += 1
        return [list(r) for r in self.tabs.get(worksheet, [])]

    def replace_rows(self, worksheet: str, rows: list[list[str]]) -> None:
        self.tabs[worksheet] = [list(r) for r in rows]

    def append_rows(self, worksheet: str, rows: list[list[str]]) -> None:
        self.tabs.setdefault(worksheet, []).extend(list(r) for r in rows)


def test_round_trip() -> None:
    client = FakeSheetsClient()
    store = SheetsStore(client, cache_ttl_seconds=0)
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


def test_list_uses_cache_within_ttl() -> None:
    client = FakeSheetsClient()
    counter = count()

    def clock() -> float:
        # First call seeds, subsequent calls advance by 1s each invocation.
        return next(counter) * 1.0

    store = SheetsStore(client, cache_ttl_seconds=10, clock=clock)
    store.list()  # cache miss
    store.list()  # cache hit
    store.list()  # cache hit
    assert client.read_calls == 1


def test_list_refreshes_after_ttl() -> None:
    client = FakeSheetsClient()
    now = [0.0]

    def clock() -> float:
        return now[0]

    store = SheetsStore(client, cache_ttl_seconds=10, clock=clock)
    store.list()
    now[0] = 5.0
    store.list()  # still inside TTL
    now[0] = 100.0
    store.list()  # outside TTL
    assert client.read_calls == 2


def test_upsert_invalidates_via_replace() -> None:
    client = FakeSheetsClient()
    store = SheetsStore(client, cache_ttl_seconds=99999)
    store.upsert(Assignment(seat_id="5-T-01", floor="tlv-floor-5", employee_email="a@x"))
    store.upsert(Assignment(seat_id="5-T-01", floor="tlv-floor-5", employee_email="b@x"))
    rows = store.list()
    assert rows[0].employee_email == "b@x"


def test_by_email() -> None:
    client = FakeSheetsClient()
    store = SheetsStore(client, cache_ttl_seconds=0)
    store.upsert_many(
        [
            Assignment(seat_id="5-T-01", floor="tlv-floor-5", employee_email="a@x"),
            Assignment(seat_id="5-T-02", floor="tlv-floor-5", employee_email="b@x"),
        ]
    )
    assert store.by_email("a@x").seat_id == "5-T-01"
    assert store.by_email("nobody@x") is None
    assert store.by_email("") is None


def test_upsert_many_bypasses_cache_to_avoid_clobber() -> None:
    """Qodo #4: a stale TTL snapshot must not erase concurrent writes.

    Simulate: process A reads, gets a cache. Process B writes a new seat
    directly to the sheet. Process A then upserts a different seat. The
    new seat from B must survive A's write.
    """
    client = FakeSheetsClient()
    store_a = SheetsStore(client, cache_ttl_seconds=99999)
    store_a.upsert(Assignment(seat_id="5-T-01", floor="tlv-floor-5", employee_email="a@x"))
    # Prime A's cache.
    _ = store_a.list()
    # B writes directly to the sheet (concurrent process).
    client.tabs["assignments"].append(["5-T-99", "tlv-floor-5", "b@x", "", "FALSE", "", "", ""])
    # A upserts a different seat. Must merge against fresh state, not cache.
    store_a.upsert(Assignment(seat_id="5-T-02", floor="tlv-floor-5", employee_email="c@x"))
    surviving = {a.seat_id for a in store_a.list()}
    assert {"5-T-01", "5-T-02", "5-T-99"} <= surviving


def test_audit_append_seeds_header_then_appends() -> None:
    client = FakeSheetsClient()
    audit = SheetsAuditLog(client)
    audit.append(
        AuditEntry(
            timestamp="2026-05-01T00:00:01Z",
            actor="t",
            action="assign",
            seat_id="5-T-01",
            employee_email="alice@x",
        )
    )
    audit.append(
        AuditEntry(
            timestamp="2026-05-01T00:00:02Z",
            actor="t",
            action="unassign",
            seat_id="5-T-01",
            old_employee_email="alice@x",
        )
    )
    rows = audit.all()
    assert [r.action for r in rows] == ["assign", "unassign"]


def test_audit_append_seeds_header_when_tab_is_phantom_empty() -> None:
    """Regression for #32: gspread auto-creates a tab via
    ``add_worksheet(rows=1, cols=10)`` on first touch; the read returns a
    single row of empty strings, not ``[]``. The previous guard treated
    that as "already populated" and skipped writing the header, so
    ``audit.all()`` couldn't parse subsequent rows."""
    client = FakeSheetsClient()
    client.tabs["audit-log"] = [["", "", "", "", "", "", "", "", "", ""]]
    audit = SheetsAuditLog(client)
    audit.append(
        AuditEntry(
            timestamp="2026-05-05T00:00:01Z",
            actor="t",
            action="assign",
            seat_id="5-T-01",
            employee_email="alice@x",
        )
    )
    assert client.tabs["audit-log"][0] == list(FIELDNAMES)
    rows = audit.all()
    assert len(rows) == 1
    assert rows[0].seat_id == "5-T-01"
    assert audit.for_seat("5-T-01")[0].employee_email == "alice@x"


def test_audit_for_seat_filters() -> None:
    client = FakeSheetsClient()
    audit = SheetsAuditLog(client)
    audit.append_many(
        [
            AuditEntry(
                timestamp="t1",
                actor="t",
                action="assign",
                seat_id="5-T-01",
                employee_email="a@x",
            ),
            AuditEntry(
                timestamp="t2",
                actor="t",
                action="assign",
                seat_id="5-T-02",
                employee_email="b@x",
            ),
        ]
    )
    history = audit.for_seat("5-T-01")
    assert len(history) == 1
    assert history[0].employee_email == "a@x"


def test_gspread_missing_raises_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """If gspread isn't installed, GspreadClient must surface OfficeError."""
    import builtins

    real_import = builtins.__import__

    def block_gspread(name, *args, **kwargs):
        if name == "gspread":
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", block_gspread)

    from office_cli.cli._errors import OfficeError
    from office_cli.seats.sheets import GspreadClient

    with pytest.raises(OfficeError) as exc:
        GspreadClient(spreadsheet_id="x", service_account_path=None)  # type: ignore[arg-type]
    assert "gspread is not installed" in exc.value.message
