"""Unified CLI entry point for office.

Noun-based command groups and globals are registered here. Top-level globals
(``learn``, ``explain``, ``whoami``) live under
:mod:`office_cli.cli._commands`; per-noun groups follow the same pattern.

Error-propagation contract: every handler raises
:class:`office_cli.cli._errors.OfficeError` on failure; :func:`main` catches
it via :func:`_dispatch` and routes through :mod:`office_cli.cli._output`.
Unknown exceptions are wrapped so no Python traceback leaks.
"""

from __future__ import annotations

import argparse
import sys

from office_cli import __version__
from office_cli.cli._commands import explain as _explain_cmd
from office_cli.cli._commands import learn as _learn_cmd
from office_cli.cli._commands import whoami as _whoami_cmd
from office_cli.cli._errors import EXIT_USER_ERROR, OfficeError
from office_cli.cli._output import emit_error


class _ArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that emits errors via our structured format."""

    def error(self, message: str) -> None:  # type: ignore[override]
        err = OfficeError(
            code=EXIT_USER_ERROR,
            message=message,
            remediation=f"run '{self.prog} --help' to see valid arguments",
        )
        emit_error(err, json_mode=False)
        raise SystemExit(err.code)


def _build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="office",
        description="office — CLI to manage sittings and meeting rooms in office maps.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    _learn_cmd.register(sub)
    _explain_cmd.register(sub)
    _whoami_cmd.register(sub)
    # Register noun groups here:
    #   from office_cli.cli._commands import seat as _seat_group
    #   _seat_group.register(sub)

    return parser


def _dispatch(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    try:
        return args.func(args)
    except OfficeError as err:
        emit_error(err, json_mode=json_mode)
        return err.code
    except Exception as err:  # noqa: BLE001 - last-resort
        wrapped = OfficeError(
            code=EXIT_USER_ERROR,
            message=f"unexpected: {err.__class__.__name__}: {err}",
            remediation="file a bug at https://github.com/agentculture/office-agent/issues",
        )
        emit_error(wrapped, json_mode=json_mode)
        return wrapped.code


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    return _dispatch(args)


if __name__ == "__main__":
    sys.exit(main())
