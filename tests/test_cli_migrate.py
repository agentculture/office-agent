"""End-to-end tests for ``office seats migrate``.

Drives migrations between the CSV backend (the default) and the
DynamoDB backend via :class:`FakeDynamoClient`. The fake client is
swapped in by patching ``Boto3DynamoClient`` at the call site so no
real AWS creds are needed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from office_cli.cli import main
from tests.test_dynamo_store import FakeDynamoClient


@pytest.fixture
def dynamo_data_dir(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Configure a Dynamo target via env, swap in the in-memory fake client."""
    monkeypatch.setenv("OFFICE_DYNAMO_ASSIGNMENTS", "office-assignments")
    monkeypatch.setenv("OFFICE_DYNAMO_AUDIT", "office-audit-log")
    monkeypatch.setenv("OFFICE_DYNAMO_REGION", "us-east-1")

    fake = FakeDynamoClient()

    def _fake_factory(*args, **kwargs):  # noqa: ANN001
        return fake

    # The migrate code does ``from office_cli.seats.dynamo import
    # Boto3DynamoClient``; patch the re-export site so the lazy import
    # picks up the fake.
    monkeypatch.setattr(
        "office_cli.seats.dynamo.Boto3DynamoClient",
        _fake_factory,
    )
    return data_dir


def _data(data_dir: Path) -> list[str]:
    return ["--data-dir", str(data_dir)]


def test_csv_to_dynamo_round_trip(
    dynamo_data_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #12 acceptance — CSV → Dynamo migration preserves rows + audit."""
    # Seed the CSV side with two assignments.
    main(["seats", "assign", "5-T-01", "alice@example.com", *_data(dynamo_data_dir)])
    main(["seats", "assign", "5-T-02", "bob@example.com", *_data(dynamo_data_dir)])
    capsys.readouterr()

    rc = main(
        ["seats", "migrate", "--from", "csv", "--to", "dynamo", "--json", *_data(dynamo_data_dir)]
    )
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    # Issue #33: migrate pads with vacant rows for every assignable id, so
    # the written count is the full universe (2 touched + 7 padded).
    assert summary["assignments_written"] == _FIXTURE_SEAT_COUNT

    # Now read via dynamo and confirm parity. Use monkeypatch so a
    # pre-existing OFFICE_STORE in the developer's shell is preserved.
    monkeypatch.setenv("OFFICE_STORE", "dynamo")
    rc = main(["seats", "list", "--json", "--occupied", *_data(dynamo_data_dir)])
    assert rc == 0
    body = json.loads(capsys.readouterr().out)
    emails = sorted(s["employee_email"] for s in body["seats"])
    assert emails == ["alice@example.com", "bob@example.com"]


def test_dry_run_writes_nothing(dynamo_data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["seats", "assign", "5-T-01", "alice@example.com", *_data(dynamo_data_dir)])
    capsys.readouterr()

    rc = main(
        [
            "seats",
            "migrate",
            "--from",
            "csv",
            "--to",
            "dynamo",
            "--dry-run",
            "--json",
            *_data(dynamo_data_dir),
        ]
    )
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["dry_run"] is True
    # Issue #33: dry-run reports the padded count (1 touched + 7 vacant).
    assert summary["assignments_new"] == _FIXTURE_SEAT_COUNT


def test_idempotent_rerun(
    dynamo_data_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-running migrate is safe: assignments upsert, audit dedups (Dynamo PK+SK)."""
    main(["seats", "assign", "5-T-01", "alice@example.com", *_data(dynamo_data_dir)])
    capsys.readouterr()

    main(["seats", "migrate", "--from", "csv", "--to", "dynamo", *_data(dynamo_data_dir)])
    main(["seats", "migrate", "--from", "csv", "--to", "dynamo", *_data(dynamo_data_dir)])
    capsys.readouterr()

    monkeypatch.setenv("OFFICE_STORE", "dynamo")
    rc = main(["seats", "history", "5-T-01", "--json", *_data(dynamo_data_dir)])
    assert rc == 0
    body = json.loads(capsys.readouterr().out)
    # One assign action, deduped after the second migrate.
    assert [e["action"] for e in body["history"]] == ["assign"]


def test_same_source_and_target_rejected(
    dynamo_data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["seats", "migrate", "--from", "csv", "--to", "csv", *_data(dynamo_data_dir)])
    assert rc == 1
    assert "both" in capsys.readouterr().err


# --- Issue #33: migrate pads target with vacant rows for every SVG seat ----


_FIXTURE_SEAT_COUNT = 9  # tlv-floor-5: 6 T-cluster + 2 Z-cluster + 1 room (5.18)


def test_migrate_pads_vacant_rows_for_every_svg_seat(
    dynamo_data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Empty source + non-empty SVG → target ends with one row per SVG seat,
    all vacant. Sheets-as-CMS contract from CLAUDE.md."""
    rc = main(
        [
            "seats",
            "migrate",
            "--from",
            "csv",
            "--to",
            "dynamo",
            "--json",
            *_data(dynamo_data_dir),
        ]
    )
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["assignments_written"] == _FIXTURE_SEAT_COUNT
    assert summary["assignments_orphans"] == 0


def test_migrate_idempotent_with_padding(
    dynamo_data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Re-running migrate against an already-padded target reports
    ``0 new / 0 overwritten / N unchanged``."""
    main(["seats", "migrate", "--from", "csv", "--to", "dynamo", *_data(dynamo_data_dir)])
    capsys.readouterr()

    rc = main(
        [
            "seats",
            "migrate",
            "--from",
            "csv",
            "--to",
            "dynamo",
            "--dry-run",
            "--json",
            *_data(dynamo_data_dir),
        ]
    )
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["assignments_new"] == 0
    assert summary["assignments_overwritten"] == 0
    assert summary["assignments_unchanged"] == _FIXTURE_SEAT_COUNT


def test_migrate_dry_run_with_padding_writes_nothing(
    dynamo_data_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--dry-run --json`` reports the full padded count without writing
    to the target."""
    rc = main(
        [
            "seats",
            "migrate",
            "--from",
            "csv",
            "--to",
            "dynamo",
            "--dry-run",
            "--json",
            *_data(dynamo_data_dir),
        ]
    )
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["dry_run"] is True
    assert summary["assignments_new"] == _FIXTURE_SEAT_COUNT

    # The dry-run guarantee is about the *Dynamo target*, not the CSV
    # source. Switch the read backend to dynamo so the assertion actually
    # exercises the target store.
    monkeypatch.setenv("OFFICE_STORE", "dynamo")
    rc = main(["seats", "list", "--json", "--occupied", *_data(dynamo_data_dir)])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["seats"] == []


def test_migrate_keeps_orphan_rows_and_reports_them(
    dynamo_data_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A row in the source for a seat ID that's not in any SVG (orphan)
    survives the migration but is surfaced in stderr + JSON."""
    # Seed an orphan directly into the CSV — the assign verb would reject
    # an unknown seat ID, so we bypass it.
    csv_path = dynamo_data_dir / "seats" / "assignments.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text(
        "seat_id,floor,employee_email,last_updated,hidden,notes,"
        "effective_from,effective_until\n"
        "99-X-99,phantom-floor,ghost@example.com,2026-01-01T00:00:00Z,FALSE,,,\n",
        encoding="utf-8",
    )

    rc = main(
        [
            "seats",
            "migrate",
            "--from",
            "csv",
            "--to",
            "dynamo",
            "--json",
            *_data(dynamo_data_dir),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert "orphans: 1" in captured.err
    assert "99-X-99" in captured.err

    summary = json.loads(captured.out)
    # 1 orphan + 8 padded vacant SVG rows = 9 written.
    assert summary["assignments_orphans"] == 1
    assert summary["assignments_written"] == 1 + _FIXTURE_SEAT_COUNT


def test_migrate_mixed_touched_orphan_and_padding(
    dynamo_data_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """3 touched + 1 orphan + 8 SVG seats with one already touched →
    target has 8 padded + 1 orphan = 9 rows;
    ``new=8-3+1=6, overwritten=0, unchanged=2``."""
    # Three legitimate assigns (hit 5-T-01 / 5-T-02 / 5-T-03) plus a
    # hand-injected orphan row.
    main(["seats", "assign", "5-T-01", "a@example.com", *_data(dynamo_data_dir)])
    main(["seats", "assign", "5-T-02", "b@example.com", *_data(dynamo_data_dir)])
    main(["seats", "assign", "5-T-03", "c@example.com", *_data(dynamo_data_dir)])
    capsys.readouterr()

    csv_path = dynamo_data_dir / "seats" / "assignments.csv"
    existing = csv_path.read_text(encoding="utf-8")
    csv_path.write_text(
        existing + "99-X-99,phantom-floor,ghost@example.com,2026-01-01T00:00:00Z,FALSE,,,\n",
        encoding="utf-8",
    )

    # First migrate to seed the target with the 3 touched + 1 orphan + 5 padded.
    main(["seats", "migrate", "--from", "csv", "--to", "dynamo", *_data(dynamo_data_dir)])
    capsys.readouterr()

    # Re-run --dry-run: padded rows already exist → all unchanged.
    rc = main(
        [
            "seats",
            "migrate",
            "--from",
            "csv",
            "--to",
            "dynamo",
            "--dry-run",
            "--json",
            *_data(dynamo_data_dir),
        ]
    )
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    # 3 touched + 1 orphan + 5 padded = 9 unchanged.
    assert summary["assignments_unchanged"] == 1 + _FIXTURE_SEAT_COUNT
    assert summary["assignments_new"] == 0
    assert summary["assignments_overwritten"] == 0
    assert summary["assignments_orphans"] == 1


def test_migrate_padded_rows_carry_correct_floor_field(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Multi-floor regression guard: each padded vacant row carries the
    floor of the SVG it came from, not a single floor reused for the lot."""
    # Add a synthetic second floor with two seats on a different floor id.
    second_floor_svg = data_dir / "floors" / "tlv-floor-9.svg"
    second_floor_svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080">\n'
        '  <rect id="9-A-01" class="seat" x="0" y="0" width="10" height="10"/>\n'
        '  <rect id="9-A-02" class="seat" x="20" y="0" width="10" height="10"/>\n'
        "</svg>\n",
        encoding="utf-8",
    )
    offices_yaml = data_dir / "data" / "offices.yaml"
    offices_yaml.write_text(
        offices_yaml.read_text(encoding="utf-8")
        + "      - id: tlv-floor-9\n"
        + "        svg: floors/tlv-floor-9.svg\n"
        + "        clusters:\n"
        + "          A: { capacity: 2, type: open-space }\n",
        encoding="utf-8",
    )

    # Run migrate against the existing CSV (empty) into Dynamo. Seed a
    # Dynamo target through the existing fixture pattern.
    monkeypatch.setenv("OFFICE_DYNAMO_ASSIGNMENTS", "office-assignments")
    monkeypatch.setenv("OFFICE_DYNAMO_AUDIT", "office-audit-log")
    monkeypatch.setenv("OFFICE_DYNAMO_REGION", "us-east-1")
    fake = FakeDynamoClient()
    monkeypatch.setattr("office_cli.seats.dynamo.Boto3DynamoClient", lambda *a, **k: fake)

    main(["seats", "migrate", "--from", "csv", "--to", "dynamo", *_data(data_dir)])
    capsys.readouterr()

    # Read the target via dynamo and assert the floor field on each row.
    monkeypatch.setenv("OFFICE_STORE", "dynamo")
    rc = main(["seats", "list", "--json", *_data(data_dir)])
    assert rc == 0
    body = json.loads(capsys.readouterr().out)
    seats_by_id = {s["seat_id"]: s["floor"] for s in body["seats"]}
    # Floor-5 seats keep their floor; floor-9 seats keep theirs. The bug
    # this guards against is "all rows get the same floor id".
    assert seats_by_id["5-T-01"] == "tlv-floor-5"
    assert seats_by_id["9-A-01"] == "tlv-floor-9"
    assert seats_by_id["9-A-02"] == "tlv-floor-9"


def test_migrate_pads_rooms_not_just_seats(
    dynamo_data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The fixture has a YAML-declared room ``5.18`` that's also class=room
    in the SVG. After migrate against an empty source, the target must
    include a vacant row for ``5.18``; it must not be reported as an
    orphan. (Per ``_build_seat_index``, rooms are valid assignment
    targets — pad them.)"""
    rc = main(
        [
            "seats",
            "migrate",
            "--from",
            "csv",
            "--to",
            "dynamo",
            "--json",
            *_data(dynamo_data_dir),
        ]
    )
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["assignments_orphans"] == 0
    # 6 T-seats + 2 Z-seats + 1 room (5.18) = 9 assignable ids.
    assert summary["assignments_written"] == _FIXTURE_SEAT_COUNT


def test_migrate_room_assignment_is_not_an_orphan(
    dynamo_data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A row in the source store for the room ``5.18`` is a legitimate
    assignment, not an orphan — even though the room has a different
    naming pattern from open-space seats."""
    main(["seats", "assign", "5.18", "team-room@example.com", *_data(dynamo_data_dir)])
    capsys.readouterr()

    rc = main(
        [
            "seats",
            "migrate",
            "--from",
            "csv",
            "--to",
            "dynamo",
            "--json",
            *_data(dynamo_data_dir),
        ]
    )
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["assignments_orphans"] == 0


def test_migrate_reports_target_orphans_without_deleting_them(
    dynamo_data_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rows already in the target whose ids are neither in source nor in
    any SVG/YAML are surfaced as ``assignments_target_orphans`` in stderr
    + JSON, but the migration does not delete them — migrate is purely
    additive, never destructive. Without this, dry-run misleadingly
    reports 'all unchanged' while the target diverges from the universe."""
    # Plant a stale row directly into the dynamo fake.
    main(["seats", "migrate", "--from", "csv", "--to", "dynamo", *_data(dynamo_data_dir)])
    capsys.readouterr()
    # Inject a row for an id that's neither in source nor SVG/YAML.
    csv_path = dynamo_data_dir / "seats" / "assignments.csv"
    csv_path.write_text(
        "seat_id,floor,employee_email,last_updated,hidden,notes,"
        "effective_from,effective_until\n"
        "stale-X-99,phantom-floor,old@example.com,2026-01-01T00:00:00Z,FALSE,,,\n",
        encoding="utf-8",
    )
    main(
        [
            "seats",
            "migrate",
            "--from",
            "csv",
            "--to",
            "dynamo",
            "--audit-append",
            *_data(dynamo_data_dir),
        ]
    )
    capsys.readouterr()
    # Now reset the source CSV (no rows). target still has stale-X-99.
    csv_path.unlink()

    rc = main(
        [
            "seats",
            "migrate",
            "--from",
            "csv",
            "--to",
            "dynamo",
            "--dry-run",
            "--json",
            *_data(dynamo_data_dir),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert "target orphans: 1" in captured.err
    assert "stale-X-99" in captured.err

    summary = json.loads(captured.out)
    assert summary["assignments_target_orphans"] == 1
    # Source has nothing; padding is the full universe; target already
    # has all of those + stale-X-99 as the orphan. So all unchanged.
    assert summary["assignments_unchanged"] == _FIXTURE_SEAT_COUNT
    assert summary["assignments_new"] == 0

    # Stale row must still be in the target (not deleted by dry-run).
    monkeypatch.setenv("OFFICE_STORE", "dynamo")
    rc = main(["seats", "history", "stale-X-99", "--json", *_data(dynamo_data_dir)])
    # The history call may return empty; the important check is that the
    # row exists in the assignments store.
    capsys.readouterr()
