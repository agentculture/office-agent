"""CLI-level tests for `office serve`."""

from __future__ import annotations

import pytest

from office_cli.cli import main


def test_help_smoke(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["serve", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "FastAPI" in out
    assert "office-cli[web]" in out


def test_default_host_and_port_in_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["serve", "--help"])
    out = capsys.readouterr().out
    assert "127.0.0.1" in out
    assert "8000" in out


def test_missing_uvicorn_extra_raises(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without uvicorn installed, `office serve` surfaces an OfficeError
    with a clear remediation. We patch the lazy import inside
    ``office_cli.server._serve``.
    """
    import builtins

    real_import = builtins.__import__

    def block_uvicorn(name, *args, **kwargs):
        if name == "uvicorn":
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", block_uvicorn)
    # We can't run the full serve flow (it would block); call run_server
    # directly through the public re-export and assert the error shape.
    from office_cli.cli._errors import OfficeError
    from office_cli.server import run_server

    with pytest.raises(OfficeError) as exc:
        run_server(object(), host="127.0.0.1", port=0)
    assert "uvicorn is not installed" in exc.value.message
    assert "office-cli[web]" in exc.value.remediation
