"""``office slack-serve`` — run the Slack ``/whereis`` Socket Mode listener.

Blocks until the process is interrupted. Configuration is env-first so
operators can drop the verb into a systemd / docker entry point without
juggling flags; ``--bot-token`` / ``--app-token`` overrides exist for
local dev.
"""

from __future__ import annotations

import argparse
import os

from office_cli._config import add_data_dir_arg, resolve_data_dir
from office_cli.cli._errors import EXIT_ENV_ERROR, OfficeError
from office_cli.cli._output import emit_diagnostic
from office_cli.seats import build_service


def cmd_slack_serve(args: argparse.Namespace) -> int:
    bot_token = (args.bot_token or os.environ.get("SLACK_BOT_TOKEN") or "").strip()
    app_token = (args.app_token or os.environ.get("SLACK_APP_TOKEN") or "").strip()
    if not bot_token:
        raise OfficeError(
            code=EXIT_ENV_ERROR,
            message="SLACK_BOT_TOKEN is empty",
            remediation=(
                "set SLACK_BOT_TOKEN (xoxb-…) in the env or pass --bot-token. "
                "The bot needs the `commands`, `users:read.email`, and "
                "`chat:write` scopes."
            ),
        )
    if not app_token:
        raise OfficeError(
            code=EXIT_ENV_ERROR,
            message="SLACK_APP_TOKEN is empty",
            remediation=(
                "set SLACK_APP_TOKEN (xapp-…) in the env or pass --app-token. "
                "Socket Mode needs an app-level token from the Slack app's "
                "Basic Information page."
            ),
        )

    raw_command = os.environ.get("OFFICE_SLACK_COMMAND")
    if raw_command is None:
        command_name = "/whereis"
    else:
        command_name = raw_command.strip()
        if not command_name:
            raise OfficeError(
                code=EXIT_ENV_ERROR,
                message="OFFICE_SLACK_COMMAND is empty",
                remediation=(
                    "unset OFFICE_SLACK_COMMAND to keep the default /whereis, "
                    "or set it to a /-prefixed slash-command name (e.g. /ai)."
                ),
            )

    data_dir = resolve_data_dir(args)
    service = build_service(data_dir, actor="slack")

    # #38: parse the directory env vars before slack-bolt construction
    # so a misconfigured TTL surfaces as an EXIT_ENV_ERROR rather than
    # being masked by a downstream BoltError when the App's auth.test
    # fires on a real network call.
    directory_enabled = parse_directory_enabled_env()
    ttl_seconds = _parse_ttl_env(os.environ.get("OFFICE_SLACK_DIRECTORY_TTL"))

    # slack_bolt is imported lazily inside `build_app` / `run_socket_mode`
    # so a missing extra surfaces as a clear OfficeError.
    try:
        from slack_bolt import App
    except ImportError as err:
        raise OfficeError(
            code=EXIT_ENV_ERROR,
            message="slack-bolt is not installed",
            remediation=("install the slack extra: pip install office-cli[slack]"),
        ) from err
    from office_cli.slack import SlackUserDirectory, build_app, run_socket_mode

    app = App(token=bot_token)

    slack_directory = SlackUserDirectory(
        app.client, enabled=directory_enabled, cache_ttl_seconds=ttl_seconds
    )
    if not directory_enabled:
        emit_diagnostic(
            "OFFICE_SLACK_DIRECTORY=disabled — name resolution falls back to "
            "email / @mention only (no users.list lookup)."
        )

    # Pass ``data_dir`` so build_app auto-resolves the roles map from
    # ``data/offices.yaml``. Without this, every Slack caller would be
    # treated as ``viewer`` regardless of the editor/planning lists.
    build_app(
        service,
        app=app,
        data_dir=data_dir,
        slack_directory=slack_directory,
        command_name=command_name,
    )
    emit_diagnostic(f"Slack {command_name} listener starting (Socket Mode)…")
    run_socket_mode(app, app_token)
    return 0


_DEFAULT_TTL_SECONDS = 300


def parse_directory_enabled_env() -> bool:
    """Wrapper around the slack-package helper so this module doesn't
    have to import :mod:`office_cli.slack` for what should be a pure
    string parse — keeps the early-validation path free of slack-bolt
    side effects."""
    from office_cli.slack._directory import parse_directory_enabled

    return parse_directory_enabled(os.environ.get("OFFICE_SLACK_DIRECTORY"))


def _parse_ttl_env(raw: str | None) -> int:
    """Read ``OFFICE_SLACK_DIRECTORY_TTL``. Default 300s; non-positive
    ints or unparseable values raise ``OfficeError`` so a misconfigured
    deployment fails loudly at startup rather than silently caching
    forever (or hammering the API every request)."""
    if raw is None or not raw.strip():
        return _DEFAULT_TTL_SECONDS
    try:
        value = int(raw.strip())
    except ValueError as err:
        raise OfficeError(
            code=EXIT_ENV_ERROR,
            message=f"OFFICE_SLACK_DIRECTORY_TTL must be an integer; got {raw!r}",
            remediation="set OFFICE_SLACK_DIRECTORY_TTL to a positive number of seconds",
        ) from err
    if value <= 0:
        raise OfficeError(
            code=EXIT_ENV_ERROR,
            message=f"OFFICE_SLACK_DIRECTORY_TTL must be > 0; got {value}",
            remediation="pick a TTL ≥ 1 second, or unset to use the 300s default",
        )
    return value


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "slack-serve",
        help="Run the Slack /whereis listener (Socket Mode).",
        description=(
            "Blocking Socket Mode listener that wires Slack /whereis to "
            "office_cli.seats.SeatService. Requires the [slack] extra "
            "and both SLACK_BOT_TOKEN (xoxb-…) and SLACK_APP_TOKEN (xapp-…)."
        ),
    )
    p.add_argument(
        "--bot-token",
        help="Override SLACK_BOT_TOKEN (xoxb-…); otherwise falls back to the env var.",
    )
    p.add_argument(
        "--app-token",
        help="Override SLACK_APP_TOKEN (xapp-…); otherwise falls back to the env var.",
    )
    add_data_dir_arg(p)
    p.set_defaults(func=cmd_slack_serve)
