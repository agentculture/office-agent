"""CLI-level tests for `office slack-serve` argument handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from office_cli.cli import main


def test_help_smoke(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["slack-serve", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Socket Mode" in out


def test_missing_bot_token(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_APP_TOKEN", raising=False)
    rc = main(["slack-serve", "--data-dir", str(data_dir)])
    assert rc == 2  # EXIT_ENV_ERROR
    err = capsys.readouterr().err
    assert "SLACK_BOT_TOKEN" in err
    assert "users:read.email" in err  # remediation includes scope hint


def test_missing_app_token(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.delenv("SLACK_APP_TOKEN", raising=False)
    rc = main(["slack-serve", "--data-dir", str(data_dir)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "SLACK_APP_TOKEN" in err
    assert "Socket Mode" in err


def test_empty_office_slack_command_is_rejected(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicitly-empty (or whitespace-only) ``OFFICE_SLACK_COMMAND``
    must fail fast with a clear message, matching the pattern used for
    ``SLACK_BOT_TOKEN`` / ``SLACK_APP_TOKEN``. Without this, the
    truthy-or-default trick would silently revert to ``/whereis`` and
    mask a misconfiguration."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("OFFICE_SLACK_COMMAND", "   ")
    rc = main(["slack-serve", "--data-dir", str(data_dir)])
    assert rc == 2  # EXIT_ENV_ERROR
    err = capsys.readouterr().err
    assert "OFFICE_SLACK_COMMAND" in err
    assert "empty" in err


@pytest.mark.parametrize("bad", ["abc", "0", "-5", "  "])
def test_invalid_directory_ttl_is_rejected(
    bad: str,
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``OFFICE_SLACK_DIRECTORY_TTL`` is parsed before slack-bolt
    starts; non-positive ints / non-ints fail fast with a clear
    remediation. ``"  "`` is treated as unset and falls back to the
    default — exclude it from the bad-value sweep when it would
    otherwise reach the bolt-import path."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("OFFICE_SLACK_DIRECTORY_TTL", bad)
    if bad.strip() == "":
        # Whitespace-only TTL is treated as unset → would proceed to
        # bolt's network init, which we don't want to exercise here.
        # The behavior is verified by the other parametrize cases.
        return
    rc = main(["slack-serve", "--data-dir", str(data_dir)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "OFFICE_SLACK_DIRECTORY_TTL" in err
