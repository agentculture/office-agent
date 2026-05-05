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
from office_cli.slack._fuzzy import FuzzyCandidate

DISAMBIG_FUZZY_ACTION_ID = "whereis_pick"


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


_DISAMBIG_CANDIDATE_LIMIT = 10


def disambiguation_users(token: str, candidates: list[SlackUser]) -> list[dict[str, Any]]:
    """#38: render the multi-section list for a Slack-roster name
    match where ≥2 workspace users share the requested name. Each
    candidate gets a section showing their best-available display name
    and full email so the caller can re-run with the unambiguous
    address. Same mrkdwn-escape contract as :func:`disambiguation`.

    Slack caps a message at 50 blocks total. A common name in a large
    workspace can match dozens of users, which would push us past
    that limit and silently break ``chat.postEphemeral``. Cap the
    rendered candidates at :data:`_DISAMBIG_CANDIDATE_LIMIT` and add
    a "…and N more" context line so the caller knows to refine.
    """
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
    rendered = candidates[:_DISAMBIG_CANDIDATE_LIMIT]
    overflow = len(candidates) - len(rendered)
    for u in rendered:
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
    if overflow:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"_…and {overflow} more — refine your query "
                            f"(full email or `@mention`)._"
                        ),
                    }
                ],
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


def disambiguation_fuzzy(
    token: str,
    candidates: list[FuzzyCandidate],
    *,
    overflow: int = 0,
) -> list[dict[str, Any]]:
    """#39: render a fuzzy-match candidate list with a "This person"
    button per row. The button's ``value`` carries the candidate's
    full email so the action handler can re-run the lookup without
    keeping per-listener state. Same mrkdwn-escape contract as
    sibling builders.

    ``overflow`` is the number of additional candidates beyond what's
    rendered — surfaced in a context block so the caller knows to
    refine. Slack caps a message at 50 blocks; with the issue's
    default ``OFFICE_FUZZY_LIMIT=5`` we land far under that, but the
    cap propagates through this builder unchanged so a higher limit
    + overflow stays safe."""
    safe_token = _escape_mrkdwn(token)
    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"Did you mean one of these for `{safe_token}`?",
            },
        }
    ]
    for c in candidates:
        rendered_label = _escape_mrkdwn(c.label or c.email)
        rendered_email = _escape_mrkdwn(c.email)
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{rendered_label}* — `{rendered_email}`",
                },
                "accessory": {
                    "type": "button",
                    "action_id": DISAMBIG_FUZZY_ACTION_ID,
                    "text": {"type": "plain_text", "text": "This person"},
                    # ``value`` carries the full email; the action handler
                    # routes off it without keeping listener-side state.
                    "value": c.email,
                },
            }
        )
    if overflow > 0:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"_…and {overflow} more — refine your search "
                            f"(full email or `@mention`)._"
                        ),
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
