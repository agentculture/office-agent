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

    data_dir = resolve_data_dir(args)
    service = build_service(data_dir, actor="slack")

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
    from office_cli.slack import build_app, run_socket_mode

    app = App(token=bot_token)
    build_app(service, app=app)
    emit_diagnostic("Slack /whereis listener starting (Socket Mode)…")
    run_socket_mode(app, app_token)
    return 0


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
        help="Override SLACK_BOT_TOKEN (xoxb-…). Env takes precedence if both unset.",
    )
    p.add_argument(
        "--app-token",
        help="Override SLACK_APP_TOKEN (xapp-…). Env takes precedence if both unset.",
    )
    add_data_dir_arg(p)
    p.set_defaults(func=cmd_slack_serve)
