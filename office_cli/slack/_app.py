"""``/whereis`` slash-command handler wired onto a slack_bolt App.

The handler is structurally typed: it expects an ``ack`` callable, a
``client`` with ``users_info`` + ``chat_postEphemeral`` methods, and a
``command`` dict. Tests pass a small ``FakeSlackContext`` instead of a
real Bolt app, so this module never needs the SDK at import time.
"""

from __future__ import annotations

from typing import Any, Callable

from office_cli.seats import SeatService
from office_cli.slack import _blocks
from office_cli.slack._resolve import ParsedTarget, parse_target


def build_app(service: SeatService, *, app: Any | None = None) -> Any:
    """Register the ``/whereis`` listener and return the configured app.

    If ``app`` is ``None`` we construct a default ``slack_bolt.App``
    (which reads ``SLACK_BOT_TOKEN`` from the env). Tests pass a fake
    app exposing only ``.command(name)``.
    """
    if app is None:
        from slack_bolt import App

        app = App()

    @app.command("/whereis")
    def _handle_whereis(ack: Callable[[], None], body: dict, command: dict, client: Any) -> None:
        ack()
        text = command.get("text", "")
        target = parse_target(text)
        blocks, label = _resolve_and_lookup(service, client, body, target)
        client.chat_postEphemeral(
            channel=body.get("channel_id", ""),
            user=body.get("user_id", ""),
            blocks=blocks,
            text=label,  # fallback for clients that ignore blocks
        )

    return app


def _resolve_and_lookup(
    service: SeatService,
    client: Any,
    body: dict,
    target: ParsedTarget,
) -> tuple[list[dict[str, Any]], str]:
    """Resolve a :class:`ParsedTarget` to an email + label and run lookup."""
    if not target.ok:
        return _blocks.parse_failed(target.raw), "couldn't parse"

    if target.email:
        email = target.email
        label = email
        return _lookup(service, email, label)

    user_id = target.user_id or body.get("user_id", "")
    if not user_id:
        return _blocks.lookup_failed("no Slack user id supplied"), "no user id"

    email, fail_reason = _email_from_user_id(client, user_id)
    if not email:
        return _blocks.lookup_failed(fail_reason), "lookup failed"
    # When the caller asked about themselves, label as "you"; otherwise
    # use the @-mention so Slack renders the name.
    label = f"<@{user_id}>" if not target.self_lookup else "you"
    return _lookup(service, email, label)


def _email_from_user_id(client: Any, user_id: str) -> tuple[str, str]:
    """Return ``(email, "")`` on success, ``("", reason)`` on failure."""
    try:
        resp = client.users_info(user=user_id)
    except Exception as err:  # noqa: BLE001 — surface as ephemeral message
        return "", f"users.info call failed ({err.__class__.__name__})"
    user = (resp or {}).get("user") or {}
    profile = user.get("profile") or {}
    email = (profile.get("email") or "").strip()
    if not email:
        return "", (
            "no email on that Slack profile (the bot needs the " "`users:read.email` scope)"
        )
    return email, ""


def _lookup(service: SeatService, email: str, label: str) -> tuple[list[dict[str, Any]], str]:
    assignment = service.whereis(email)
    if assignment is None:
        return _blocks.no_seat(label), f"no seat for {email}"
    if assignment.hidden:
        return _blocks.hidden_private(assignment, target_label=label), "occupied (private)"
    return _blocks.occupied(assignment, target_label=label), f"{label} → {assignment.seat_id}"
