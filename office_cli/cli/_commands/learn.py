"""``office learn`` — the learnability affordance.

Satisfies the agent-first rubric: >=200 chars and mentions purpose, command
map, exit codes, --json, explain.
"""

from __future__ import annotations

import argparse

from office_cli import __version__
from office_cli.cli._output import emit_result

_TEXT = """\
office — CLI to manage sittings and meeting rooms in office maps.

Purpose
-------
office is the operational surface for AgentCulture's office-agent: it owns
seat assignments and meeting-room metadata across multiple offices and
floors. Floor plans are SVGs (hand-traced from architect plans) with stable
IDs; people come from BambooHR; assignments live in a Google Sheet (v1) or
DynamoDB (v2). The CLI exposes the same operations as the Slack `/whereis`
command and the web map.

Commands
--------
  office learn              Print this self-teaching prompt. Supports --json.
  office explain <path>...  Print markdown docs for any noun/verb path.
                            Supports --json.
  office whoami             Probe authentication state. Supports --json.
  # Real verbs (seat assign, room book, where, ...) land in later versions.

Machine-readable output
-----------------------
Every command that produces a listing or report supports --json. Errors in
JSON mode emit {"code", "message", "remediation"} to stderr. Stdout and
stderr are never mixed.

Exit-code policy
----------------
  0 success
  1 user-input error (bad flag, bad path, missing arg)
  2 environment / setup error
  3 internal error (unexpected exception)
  4+ reserved

More detail
-----------
  office explain office
"""


def _as_json_payload() -> dict[str, object]:
    return {
        "tool": "office",
        "version": __version__,
        "purpose": "Manage seat assignments and meeting rooms across office floor plans.",
        "commands": [
            {"path": ["learn"], "summary": "Self-teaching prompt."},
            {"path": ["explain"], "summary": "Markdown docs by path."},
            {"path": ["whoami"], "summary": "Probe authentication state."},
        ],
        "exit_codes": {
            "0": "success",
            "1": "user-input error",
            "2": "environment/setup error",
            "3": "internal error",
        },
        "json_support": True,
        "explain_pointer": "office explain <path>",
    }


def cmd_learn(args: argparse.Namespace) -> int:
    if getattr(args, "json", False):
        emit_result(_as_json_payload(), json_mode=True)
    else:
        emit_result(_TEXT, json_mode=False)
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "learn",
        help="Print a structured self-teaching prompt for agent consumers.",
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=cmd_learn)
