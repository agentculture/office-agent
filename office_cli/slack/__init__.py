"""Slack integration for the v1 seating system.

Wraps :func:`office_cli.seats.SeatService.whereis` in a Slack Bolt app
that exposes the ``/whereis`` slash command. Two entry points:

* :func:`build_app` — register the listener on a (caller-supplied or
  newly-constructed) :class:`slack_bolt.App`. Used by the CLI verb and
  unit tests (which can pass a fake app).
* :func:`run_socket_mode` — block on Slack's Socket Mode connection.

``slack_bolt`` is **not** imported at package-load time; it is pulled
lazily inside :func:`run_socket_mode` and the default-app branch of
:func:`build_app`. That way installations without the ``[slack]`` extra
can still import :mod:`office_cli` cleanly.
"""

from __future__ import annotations

from office_cli.slack._app import build_app
from office_cli.slack._directory import (
    SlackUser,
    SlackUserDirectory,
    parse_directory_enabled,
)
from office_cli.slack._serve import run_socket_mode

__all__ = [
    "build_app",
    "run_socket_mode",
    "SlackUser",
    "SlackUserDirectory",
    "parse_directory_enabled",
]
