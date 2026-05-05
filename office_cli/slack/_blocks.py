"""Block Kit response builders for the ``/whereis`` slash command.

Every builder returns a list of `Block Kit
<https://api.slack.com/block-kit>`_ blocks suitable for
``chat.postEphemeral``'s ``blocks`` field. We never include user names
or notes when ``hidden=True`` — that's the v1 privacy contract until
Stage 7 lands roles.
"""

from __future__ import annotations

import os
from typing import Any

from office_cli.seats import Assignment


def _deep_link_button(seat_id: str, floor: str) -> dict[str, Any] | None:
    base = (os.environ.get("OFFICE_WEB_BASE_URL") or "").rstrip("/")
    if not base:
        return None
    url = f"{base}/floors/{floor}?seat={seat_id}"
    return {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Open map"},
                "url": url,
            }
        ],
    }


def occupied(
    assignment: Assignment, *, target_label: str, verb: str = "sits"
) -> list[dict[str, Any]]:
    """Render the seat-found block. ``verb`` is ``"sits"`` for third-person
    subjects (email or ``<@Uxxx>`` mention) and ``"sit"`` for second-person
    self-lookup where the handler substitutes the literal ``"you"`` for
    ``target_label``. The handler picks the verb form; the renderer just
    interpolates."""
    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{target_label}* {verb} at *{assignment.seat_id}* "
                    f"on `{assignment.floor}`."
                ),
            },
        }
    ]
    if assignment.last_updated:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"_last updated {assignment.last_updated}_",
                    }
                ],
            }
        )
    button = _deep_link_button(assignment.seat_id, assignment.floor)
    if button:
        blocks.append(button)
    return blocks


def hidden_private(assignment: Assignment, *, target_label: str) -> list[dict[str, Any]]:
    """Hidden seat — render the floor but not the email or notes."""
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{target_label}* — occupied (private) on `{assignment.floor}`.",
            },
        }
    ]


def no_seat(target_label: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"No seat assigned for *{target_label}*.",
            },
        }
    ]


def parse_failed(raw: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"Couldn't parse a person from `{raw}`. Pass an "
                    "`@mention` or an `email@address`."
                ),
            },
        }
    ]


def lookup_failed(reason: str) -> list[dict[str, Any]]:
    """Used when a Slack mention's email is missing or `users.info` fails."""
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"Couldn't resolve that person to an email: {reason}.",
            },
        }
    ]
