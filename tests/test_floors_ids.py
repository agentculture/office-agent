"""Tests for the seat/room ID contract."""

from __future__ import annotations

import pytest

from office_cli.floors._ids import is_room_id, is_seat_id, parse_seat_id


@pytest.mark.parametrize("sid", ["5-T-01", "5-T-99", "12-K-04", "1-Z-00"])
def test_seat_id_happy(sid: str) -> None:
    assert is_seat_id(sid)
    parsed = parse_seat_id(sid)
    assert str(parsed) == sid


@pytest.mark.parametrize(
    "sid",
    [
        "5-T-1",  # not zero-padded
        "5-t-01",  # cluster must be uppercase
        "5--T-01",  # extra dash
        "T-5-01",  # floor must lead
        "5-T-001",  # too long
        "5.18",  # room id, not seat id
        "5-T",  # missing num
        "",
    ],
)
def test_seat_id_rejects_malformed(sid: str) -> None:
    assert not is_seat_id(sid)
    with pytest.raises(ValueError):
        parse_seat_id(sid)


@pytest.mark.parametrize("rid", ["5.01", "5.18", "12.04"])
def test_room_id_happy(rid: str) -> None:
    assert is_room_id(rid)


@pytest.mark.parametrize("rid", ["5", "5.", ".18", "5.18.0", "room-5"])
def test_room_id_rejects_malformed(rid: str) -> None:
    assert not is_room_id(rid)
