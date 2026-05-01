"""Tests for the CSV-backed assignment store."""

from __future__ import annotations

from pathlib import Path

from office_cli.seats import Assignment, CsvStore


def test_round_trip(tmp_path: Path) -> None:
    store = CsvStore(tmp_path / "assignments.csv")
    assert store.list() == []
    a = Assignment(
        seat_id="5-T-01",
        floor="tlv-floor-5",
        employee_email="alice@example.com",
        last_updated="2026-05-01T00:00:00Z",
        hidden=True,
        notes="ergonomic",
    )
    store.upsert(a)
    again = CsvStore(tmp_path / "assignments.csv")
    rows = again.list()
    assert len(rows) == 1
    assert rows[0].seat_id == "5-T-01"
    assert rows[0].employee_email == "alice@example.com"
    assert rows[0].hidden is True


def test_upsert_replaces(tmp_path: Path) -> None:
    store = CsvStore(tmp_path / "assignments.csv")
    store.upsert(Assignment(seat_id="5-T-01", floor="tlv-floor-5", employee_email="a@x"))
    store.upsert(Assignment(seat_id="5-T-01", floor="tlv-floor-5", employee_email="b@x"))
    assert store.get("5-T-01").employee_email == "b@x"
    assert len(store.list()) == 1


def test_by_email(tmp_path: Path) -> None:
    store = CsvStore(tmp_path / "assignments.csv")
    store.upsert_many(
        [
            Assignment(seat_id="5-T-01", floor="tlv-floor-5", employee_email="a@x"),
            Assignment(seat_id="5-T-02", floor="tlv-floor-5", employee_email="b@x"),
        ]
    )
    assert store.by_email("a@x").seat_id == "5-T-01"
    assert store.by_email("nobody@x") is None
    assert store.by_email("") is None
