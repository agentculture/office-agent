"""Smoke tests for office's CLI."""

from __future__ import annotations

import pytest

from office_cli import __version__
from office_cli.cli import main


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_no_args_prints_help_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "office" in out
    assert "learn" in out
    assert "explain" in out
    assert "whoami" in out


def test_unknown_verb_emits_hint(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["zzz-not-a-real-verb"])
    assert exc.value.code != 0
    err = capsys.readouterr().err
    assert "error:" in err
    assert "hint:" in err


def test_explain_unknown_path_fails_with_hint(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = main(["explain", "zzz-not-a-real-noun"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "error:" in err
    assert "hint:" in err
