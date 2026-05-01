"""Blocking entry point for Slack Socket Mode.

Lazy-imports ``slack_bolt`` and ``slack_sdk.socket_mode`` so installs
without the ``[slack]`` extra still load the parent package cleanly.
"""

from __future__ import annotations

from typing import Any

from office_cli.cli._errors import EXIT_ENV_ERROR, OfficeError


def run_socket_mode(app: Any, app_token: str) -> None:
    """Block until the process is interrupted.

    Raises :class:`OfficeError` (``EXIT_ENV_ERROR``) if the SDK is
    missing or the token is empty, so the CLI verb can render a
    consistent remediation hint.
    """
    if not app_token:
        raise OfficeError(
            code=EXIT_ENV_ERROR,
            message="SLACK_APP_TOKEN is empty",
            remediation=(
                "Socket Mode needs an app-level token (xapp-…). "
                "Set SLACK_APP_TOKEN or pass --app-token."
            ),
        )
    try:
        from slack_bolt.adapter.socket_mode import SocketModeHandler
    except ImportError as err:
        raise OfficeError(
            code=EXIT_ENV_ERROR,
            message="slack-bolt is not installed",
            remediation=("install the slack extra: pip install office-cli[slack]"),
        ) from err
    SocketModeHandler(app, app_token).start()
