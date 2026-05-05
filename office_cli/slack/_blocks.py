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
from office_cli.slack._directory import SlackUser


def _escape_mrkdwn(s: str) -> str:
    """Escape Slack mrkdwn control characters in user-supplied text.

    Slack mrkdwn parses ``<…>`` as a special link / mention sequence
    (``<!here>``, ``<@U…>``, ``<#C…>``, ``<https://…>``), so an
    unescaped ``<`` from a user-supplied token can ping the channel or
    rewrite the message. ``&`` is the HTML-entity prefix and must be
    escaped first or we'd double-escape ``<`` / ``>`` below. Backticks
    cannot be escaped inside a code span, so we replace them with a
    single quote — visual approximation, no parser confusion.

    Apply to anything that flows from the slash-command argument into
    a rendered block. Slack's ``text`` fallback is *also* parsed for
    these sequences when blocks aren't rendered; the handler keeps
    user tokens out of that field entirely as a separate defense.
    """
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("`", "'")


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
                    f"Couldn't parse a person from `{raw}`. Pass a name "
                    "(`alice` or `ori.nachum`), an `@mention`, or an "
                    "`email@address`."
                ),
            },
        }
    ]


def no_match_for_token(token: str) -> list[dict[str, Any]]:
    """No assignment matched the bare-token local-part (#29 MVP)."""
    safe = _escape_mrkdwn(token)
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"Couldn't find a seat for `{safe}`. Try the full "
                    "`email@address` or an `@mention`."
                ),
            },
        }
    ]


def disambiguation(token: str, matches: list[Assignment]) -> list[dict[str, Any]]:
    """Multi-section list when ``find_by_local_part`` returned ≥2
    candidates (#29 MVP). Each ``Assignment`` gets a section block
    showing its email + seat. Redacted entries follow the same
    contract as :func:`hidden_private` — only the floor is shown, not
    the seat id, so a viewer-role caller can see *that* there's a
    private match without learning where it sits."""
    safe_token = _escape_mrkdwn(token)
    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"Multiple seats matched `{safe_token}`:",
            },
        }
    ]
    for a in matches:
        if a.redacted:
            # Match hidden_private's privacy contract: floor only, no seat_id.
            line = f"• occupied (private) on `{a.floor}`"
        else:
            line = f"• {a.employee_email} → `{a.seat_id}` on `{a.floor}`"
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": line},
            }
        )
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "_Re-run with the full email to pick one._",
                }
            ],
        }
    )
    return blocks


def disambiguation_users(token: str, candidates: list[SlackUser]) -> list[dict[str, Any]]:
    """#38: render the multi-section list for a Slack-roster name
    match where ≥2 workspace users share the requested name. Each
    candidate gets a section showing their best-available display name
    and full email so the caller can re-run with the unambiguous
    address. Same mrkdwn-escape contract as :func:`disambiguation`."""
    safe_token = _escape_mrkdwn(token)
    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"Multiple Slack users matched `{safe_token}`:",
            },
        }
    ]
    for u in candidates:
        # Prefer display_name (what people see in Slack), fall back to
        # real_name, then to ``name``. Strip + escape to keep the
        # mrkdwn parser tame on user-supplied profile fields.
        rendered_name = _escape_mrkdwn(u.display_name or u.real_name or u.name or "(unnamed)")
        rendered_email = _escape_mrkdwn(u.email)
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"• {rendered_name} — `{rendered_email}`",
                },
            }
        )
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "_Re-run with the full email to pick one._",
                }
            ],
        }
    )
    return blocks


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
