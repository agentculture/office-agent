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


@pytest.mark.parametrize("bad", ["abc", "0", "-5"])
def test_invalid_directory_ttl_is_rejected(
    bad: str,
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``OFFICE_SLACK_DIRECTORY_TTL`` is parsed before slack-bolt
    starts; non-positive ints / non-ints fail fast with a clear
    remediation, so a misconfigured deployment doesn't get masked by
    a downstream BoltError."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("OFFICE_SLACK_DIRECTORY_TTL", bad)
    rc = main(["slack-serve", "--data-dir", str(data_dir)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "OFFICE_SLACK_DIRECTORY_TTL" in err


def test_whitespace_directory_ttl_uses_default() -> None:
    """``OFFICE_SLACK_DIRECTORY_TTL="   "`` (whitespace-only) is
    treated as unset and falls back to the default. Asserted against
    the parse helper directly so the test doesn't have to spin up
    slack-bolt; the integration path is exercised by the bot-token
    happy-path tests."""
    from office_cli.cli._commands.slack_serve import _DEFAULT_TTL_SECONDS, _parse_ttl_env

    assert _parse_ttl_env("   ") == _DEFAULT_TTL_SECONDS
    assert _parse_ttl_env("") == _DEFAULT_TTL_SECONDS
    assert _parse_ttl_env(None) == _DEFAULT_TTL_SECONDS


@pytest.mark.parametrize("bad", ["abc", "2.0", "-0.1", "1.5"])
def test_invalid_fuzzy_cutoff_is_rejected(bad: str) -> None:
    """``OFFICE_FUZZY_CUTOFF`` must be a float in [0.0, 1.0]; any
    out-of-range or non-float value raises ``OfficeError`` so the
    listener fails fast."""
    from office_cli.cli._commands.slack_serve import _parse_fuzzy_cutoff_env
    from office_cli.cli._errors import OfficeError

    with pytest.raises(OfficeError) as exc:
        _parse_fuzzy_cutoff_env(bad)
    assert "OFFICE_FUZZY_CUTOFF" in exc.value.message


@pytest.mark.parametrize("good", ["0.0", "0.7", "1.0", "  0.5  "])
def test_valid_fuzzy_cutoff_parses(good: str) -> None:
    from office_cli.cli._commands.slack_serve import _parse_fuzzy_cutoff_env

    assert 0.0 <= _parse_fuzzy_cutoff_env(good) <= 1.0


def test_whitespace_fuzzy_cutoff_uses_default() -> None:
    from office_cli.cli._commands.slack_serve import _parse_fuzzy_cutoff_env
    from office_cli.slack._fuzzy import DEFAULT_CUTOFF

    assert _parse_fuzzy_cutoff_env(None) == DEFAULT_CUTOFF
    assert _parse_fuzzy_cutoff_env("") == DEFAULT_CUTOFF
    assert _parse_fuzzy_cutoff_env("   ") == DEFAULT_CUTOFF


@pytest.mark.parametrize("bad", ["abc", "0", "-3", "1.5", "26", "999"])
def test_invalid_fuzzy_limit_is_rejected(bad: str) -> None:
    """``OFFICE_FUZZY_LIMIT`` must be a positive integer at or below
    the safe cap. PR #42 review (Qodo + Copilot): without the upper
    bound, the picker can exceed Slack's 50-block cap and silently
    break ``chat.postEphemeral`` at runtime."""
    from office_cli.cli._commands.slack_serve import _parse_fuzzy_limit_env
    from office_cli.cli._errors import OfficeError

    with pytest.raises(OfficeError) as exc:
        _parse_fuzzy_limit_env(bad)
    assert "OFFICE_FUZZY_LIMIT" in exc.value.message


def test_max_fuzzy_limit_accepted() -> None:
    """The cap itself is a valid value — boundary check."""
    from office_cli.cli._commands.slack_serve import _MAX_FUZZY_LIMIT, _parse_fuzzy_limit_env

    assert _parse_fuzzy_limit_env(str(_MAX_FUZZY_LIMIT)) == _MAX_FUZZY_LIMIT


def test_whitespace_fuzzy_limit_uses_default() -> None:
    from office_cli.cli._commands.slack_serve import _parse_fuzzy_limit_env
    from office_cli.slack._fuzzy import DEFAULT_LIMIT

    assert _parse_fuzzy_limit_env(None) == DEFAULT_LIMIT
    assert _parse_fuzzy_limit_env("") == DEFAULT_LIMIT
    assert _parse_fuzzy_limit_env("   ") == DEFAULT_LIMIT
