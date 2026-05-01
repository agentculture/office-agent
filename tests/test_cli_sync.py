"""End-to-end tests for ``office seats sync``.

Drives the bi-directional reconciliation between Sheets and Dynamo
via in-memory fakes (no real AWS / Google creds).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from office_cli.cli import main
from tests.test_dynamo_store import FakeDynamoClient
from tests.test_sheets_store import FakeSheetsClient


@pytest.fixture
def sync_env(data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Configure both backends to use in-memory fakes via env + monkeypatch.

    Returns a tuple ``(data_dir, fake_dynamo, fake_sheets)`` so tests
    can inspect or seed each side directly.
    """
    sa_path = data_dir / "fake-sa.json"
    sa_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("OFFICE_SHEETS_ID", "fake-spreadsheet-id")
    monkeypatch.setenv("OFFICE_SHEETS_SA", str(sa_path))

    monkeypatch.setenv("OFFICE_DYNAMO_ASSIGNMENTS", "office-assignments")
    monkeypatch.setenv("OFFICE_DYNAMO_AUDIT", "office-audit-log")
    monkeypatch.setenv("OFFICE_DYNAMO_REGION", "us-east-1")

    fake_dynamo = FakeDynamoClient()
    fake_sheets = FakeSheetsClient()

    monkeypatch.setattr(
        "office_cli.seats.dynamo.Boto3DynamoClient",
        lambda *a, **kw: fake_dynamo,
    )
    monkeypatch.setattr(
        "office_cli.seats.sheets.GspreadClient",
        lambda *a, **kw: fake_sheets,
    )
    return data_dir, fake_dynamo, fake_sheets


def _data(data_dir: Path) -> list[str]:
    return ["--data-dir", str(data_dir)]


def _seed_sheets(data_dir: Path) -> None:
    """Seed an assignment via the CLI pointing at the sheets backend."""
    import os

    prior = os.environ.get("OFFICE_STORE")
    os.environ["OFFICE_STORE"] = "sheets"
    try:
        main(["seats", "assign", "5-T-01", "alice@example.com", *_data(data_dir)])
    finally:
        if prior is None:
            os.environ.pop("OFFICE_STORE", None)
        else:
            os.environ["OFFICE_STORE"] = prior


def test_sync_pulls_from_sheets_to_dynamo(sync_env, capsys: pytest.CaptureFixture[str]) -> None:
    data_dir, _fake_dynamo, _fake_sheets = sync_env
    _seed_sheets(data_dir)
    capsys.readouterr()

    rc = main(["seats", "sync", "--primary", "sheets", "--json", *_data(data_dir)])
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["dynamo_writes"] == 1
    assert summary["sheets_writes"] == 0


def test_sync_dry_run_writes_nothing(sync_env, capsys: pytest.CaptureFixture[str]) -> None:
    data_dir, fake_dynamo, _fake_sheets = sync_env
    _seed_sheets(data_dir)
    capsys.readouterr()

    rc = main(
        [
            "seats",
            "sync",
            "--primary",
            "sheets",
            "--dry-run",
            "--json",
            *_data(data_dir),
        ]
    )
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["dry_run"] is True
    assert summary["dynamo_writes"] == 1
    assert fake_dynamo.scan_all("office-assignments") == []


def test_sync_is_idempotent(sync_env, capsys: pytest.CaptureFixture[str]) -> None:
    data_dir, _fake_dynamo, _fake_sheets = sync_env
    _seed_sheets(data_dir)
    capsys.readouterr()

    main(["seats", "sync", "--primary", "sheets", *_data(data_dir)])
    capsys.readouterr()
    rc = main(["seats", "sync", "--primary", "sheets", "--json", *_data(data_dir)])
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["dynamo_writes"] == 0
    assert summary["sheets_writes"] == 0


def test_sync_pushes_dynamo_to_sheets_via_primary(
    sync_env, capsys: pytest.CaptureFixture[str]
) -> None:
    data_dir, fake_dynamo, _fake_sheets = sync_env
    fake_dynamo.put_item(
        "office-assignments",
        {
            "seat_id": "5-T-02",
            "floor": "tlv-floor-5",
            "employee_email": "bob@example.com",
            "last_updated": "2026-05-01T00:00:01Z",
            "hidden": False,
            "notes": "",
            "effective_from": "2026-05-01",
            "effective_until": "",
        },
    )

    rc = main(["seats", "sync", "--primary", "dynamo", "--json", *_data(data_dir)])
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["sheets_writes"] == 1


def test_invalid_primary_rejected(sync_env, capsys: pytest.CaptureFixture[str]) -> None:
    data_dir, *_ = sync_env
    with pytest.raises(SystemExit) as exc:
        main(["seats", "sync", "--primary", "csv", *_data(data_dir)])
    # The CLI's _ArgumentParser override emits OfficeError + EXIT_USER_ERROR (1).
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "invalid choice" in err
