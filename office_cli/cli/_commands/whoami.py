"""``office whoami`` — auth probe stub.

v0.0.1 always reports ``unauthenticated``. Real auth lands when whichever
back-end (BambooHR, Google Sheets, DynamoDB, Slack) gets wired up.
"""

from __future__ import annotations

import argparse

from office_cli.cli._output import emit_result

_STATUS = "unauthenticated"


def _as_json_payload() -> dict[str, object]:
    return {
        "status": _STATUS,
        "user": None,
        "backends": {
            "bamboohr": "unconfigured",
            "google_sheets": "unconfigured",
            "slack": "unconfigured",
        },
    }


def cmd_whoami(args: argparse.Namespace) -> int:
    if getattr(args, "json", False):
        emit_result(_as_json_payload(), json_mode=True)
    else:
        emit_result(_STATUS, json_mode=False)
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "whoami",
        help="Probe authentication state across configured back-ends.",
        description="Probe authentication state across configured back-ends.",
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=cmd_whoami)
