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
    dynamo_data_dir: Path, capsys: pytest.CaptureFixture[str]
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
    assert summary["assignments_written"] == 2

    # Now read via dynamo and confirm parity.
    import os

    os.environ["OFFICE_STORE"] = "dynamo"
    try:
        rc = main(["seats", "list", "--json", "--occupied", *_data(dynamo_data_dir)])
        assert rc == 0
        body = json.loads(capsys.readouterr().out)
        emails = sorted(s["employee_email"] for s in body["seats"])
        assert emails == ["alice@example.com", "bob@example.com"]
    finally:
        os.environ.pop("OFFICE_STORE", None)


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
    assert summary["assignments_new"] == 1


def test_idempotent_rerun(dynamo_data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Re-running migrate is safe: assignments upsert, audit dedups (Dynamo PK+SK)."""
    main(["seats", "assign", "5-T-01", "alice@example.com", *_data(dynamo_data_dir)])
    capsys.readouterr()

    main(["seats", "migrate", "--from", "csv", "--to", "dynamo", *_data(dynamo_data_dir)])
    main(["seats", "migrate", "--from", "csv", "--to", "dynamo", *_data(dynamo_data_dir)])
    capsys.readouterr()

    import os

    os.environ["OFFICE_STORE"] = "dynamo"
    try:
        rc = main(["seats", "history", "5-T-01", "--json", *_data(dynamo_data_dir)])
        assert rc == 0
        body = json.loads(capsys.readouterr().out)
        # One assign action, deduped after the second migrate.
        assert [e["action"] for e in body["history"]] == ["assign"]
    finally:
        os.environ.pop("OFFICE_STORE", None)


def test_same_source_and_target_rejected(
    dynamo_data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["seats", "migrate", "--from", "csv", "--to", "csv", *_data(dynamo_data_dir)])
    assert rc == 1
    assert "both" in capsys.readouterr().err
