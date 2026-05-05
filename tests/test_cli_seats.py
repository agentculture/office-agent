"""End-to-end tests for ``office seats`` commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from office_cli.cli import main


def _data(data_dir: Path) -> list[str]:
    return ["--data-dir", str(data_dir)]


def test_assign_then_list_json(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["seats", "assign", "5-T-01", "alice@example.com", *_data(data_dir)]) == 0
    capsys.readouterr()
    rc = main(["seats", "list", "--json", "--occupied", *_data(data_dir)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["seats"][0]["seat_id"] == "5-T-01"
    assert payload["seats"][0]["employee_email"] == "alice@example.com"


def test_double_assign_emits_error(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["seats", "assign", "5-T-01", "alice@example.com", *_data(data_dir)])
    capsys.readouterr()
    rc = main(["seats", "assign", "5-T-02", "alice@example.com", *_data(data_dir)])
    assert rc == 1
    captured = capsys.readouterr()
    assert "already assigned" in captured.err
    assert "hint:" in captured.err
    # Remediation must reflect the post-0.9.6 ``move`` order (seat first).
    assert "office seats move 5-T-02 alice@example.com" in captured.err


def test_move_atomic(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["seats", "assign", "5-T-01", "alice@example.com", *_data(data_dir)])
    capsys.readouterr()
    rc = main(["seats", "move", "5-T-02", "alice@example.com", *_data(data_dir)])
    assert rc == 0
    capsys.readouterr()
    rc = main(["seats", "history", "5-T-01", "--json", *_data(data_dir)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    actions = [e["action"] for e in payload["history"]]
    assert actions == ["assign", "unassign"]


def test_move_rejects_swapped_order_with_hint(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Issue #30: passing ``email seat`` (the pre-0.9.6 ``move`` order)
    is rejected with a remediation that shows the correct order,
    instead of the previous misleading
    "unknown seat: alice@example.com" error."""
    main(["seats", "assign", "5-T-01", "alice@example.com", *_data(data_dir)])
    capsys.readouterr()
    rc = main(["seats", "move", "alice@example.com", "5-T-02", *_data(data_dir)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "looks like an email" in err
    assert "office seats move 5-T-02 alice@example.com" in err
    # Service was not invoked — no audit row written for the bogus call.
    rc = main(["seats", "history", "5-T-01", "--json", *_data(data_dir)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    actions = [e["action"] for e in payload["history"]]
    assert actions == ["assign"]


def test_unassign(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["seats", "assign", "5-T-01", "alice@example.com", *_data(data_dir)])
    capsys.readouterr()
    rc = main(["seats", "unassign", "5-T-01", *_data(data_dir)])
    assert rc == 0


def test_unknown_seat_user_error(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["seats", "assign", "9-Q-99", "alice@example.com", *_data(data_dir)])
    assert rc == 1
    assert "unknown seat" in capsys.readouterr().err


def test_list_text_smoke(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["seats", "list", *_data(data_dir)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "5-T-01" in out


def test_assign_with_from_and_as_of_filter(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Issue #10 acceptance — assign --from in the future, then list --as-of."""
    rc = main(
        [
            "seats",
            "assign",
            "5-T-01",
            "alice@example.com",
            "--from",
            "2026-07-01",
            *_data(data_dir),
        ]
    )
    assert rc == 0
    capsys.readouterr()

    # --as-of before the window: row renders vacant.
    rc = main(["seats", "list", "--json", "--as-of", "2026-06-30", *_data(data_dir)])
    assert rc == 0
    seats = {s["seat_id"]: s for s in json.loads(capsys.readouterr().out)["seats"]}
    assert seats["5-T-01"]["employee_email"] is None

    # --as-of inside the window: row visible.
    rc = main(["seats", "list", "--json", "--as-of", "2026-07-15", *_data(data_dir)])
    assert rc == 0
    seats = {s["seat_id"]: s for s in json.loads(capsys.readouterr().out)["seats"]}
    assert seats["5-T-01"]["employee_email"] == "alice@example.com"


def test_assign_rejects_inverted_window(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        [
            "seats",
            "assign",
            "5-T-01",
            "alice@example.com",
            "--from",
            "2026-08-01",
            "--until",
            "2026-07-01",
            *_data(data_dir),
        ]
    )
    assert rc == 1
    assert "before" in capsys.readouterr().err


def test_list_rejects_malformed_as_of(data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["seats", "list", "--as-of", "tomorrow", *_data(data_dir)])
    assert rc == 1
    assert "--as-of" in capsys.readouterr().err


def test_bamboohr_gate_off_keeps_stdout_clean(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Selecting bamboohr without the gate flag must (a) emit the
    'gated off' warning to stderr and (b) leave stdout JSON parseable
    (Copilot review on PR #24)."""
    monkeypatch.delenv("OFFICE_BAMBOOHR_ENABLED", raising=False)
    monkeypatch.setenv("OFFICE_DIRECTORY", "bamboohr")
    monkeypatch.setenv("BAMBOOHR_SUBDOMAIN", "tipalti")
    monkeypatch.setenv("BAMBOOHR_API_TOKEN", "fake")
    rc = main(["seats", "list", "--json", *_data(data_dir)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "BambooHR backend is gated off" in captured.err
    payload = json.loads(captured.out)
    assert "seats" in payload
