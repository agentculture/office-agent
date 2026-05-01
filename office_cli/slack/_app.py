"""``/whereis`` slash-command handler wired onto a slack_bolt App.

The handler is structurally typed: it expects an ``ack`` callable, a
``client`` with ``users_info`` + ``chat_postEphemeral`` methods, and a
``command`` dict. Tests pass a small ``FakeSlackContext`` instead of a
real Bolt app, so this module never needs the SDK at import time.
"""

from __future__ import annotations

from typing import Any, Callable

from office_cli._dates import parse_iso_date, today_iso_date
from office_cli.cli._errors import OfficeError
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
        blocks, label = _resolve_and_lookup(service, client, body, command, target)
        # ``command`` is the slash-command payload and is the canonical
        # source for ``channel_id``/``user_id``; ``body`` is the Bolt-
        # wrapped envelope and may differ in some adapter shapes. Prefer
        # command, fall back to body.
        client.chat_postEphemeral(
            channel=command.get("channel_id") or body.get("channel_id", ""),
            user=command.get("user_id") or body.get("user_id", ""),
            blocks=blocks,
            text=label,  # fallback for clients that ignore blocks
        )

    return app


def _resolve_and_lookup(
    service: SeatService,
    client: Any,
    body: dict,
    command: dict,
    target: ParsedTarget,
) -> tuple[list[dict[str, Any]], str]:
    """Resolve a :class:`ParsedTarget` to an email + label and run lookup."""
    if not target.ok:
        return _blocks.parse_failed(target.raw), "couldn't parse"

    # Resolve the as-of date once — when the caller didn't pass a date,
    # default to today (matches the CLI default; the trailing-token regex
    # is permissive about month/day, so calendar-validate it explicitly).
    try:
        as_of = _resolve_as_of(service, target.as_of)
    except OfficeError as err:
        return _blocks.parse_failed(f"{target.as_of} — {err.message}"), "bad date"

    if target.email:
        email = target.email
        label = email
        return _lookup(service, email, label, as_of=as_of)

    user_id = target.user_id or command.get("user_id") or body.get("user_id", "")
    if not user_id:
        return _blocks.lookup_failed("no Slack user id supplied"), "no user id"

    email, fail_reason = _email_from_user_id(client, user_id)
    if not email:
        return _blocks.lookup_failed(fail_reason), "lookup failed"
    # When the caller asked about themselves, label as "you"; otherwise
    # use the @-mention so Slack renders the name.
    label = "you" if target.self_lookup else f"<@{user_id}>"
    return _lookup(service, email, label, as_of=as_of)


def _resolve_as_of(service: SeatService, raw: str) -> str:
    """Calendar-validate ``raw`` if non-empty, else fall back to today.

    Uses the service's clock so test injections continue to work.
    """
    if raw:
        return parse_iso_date(raw, field="as-of date", example="2026-07-01")
    return today_iso_date(service._clock)


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
        return "", ("no email on that Slack profile (the bot needs the `users:read.email` scope)")
    return email, ""


def _lookup(
    service: SeatService,
    email: str,
    label: str,
    *,
    as_of: str | None = None,
) -> tuple[list[dict[str, Any]], str]:
    # Both blocks and the `text` fallback use ``label`` so we never leak
    # the resolved profile email through the screen-reader / older-client
    # rendering path — it would defeat the redaction the blocks rely on.
    assignment = service.whereis(email, as_of=as_of)
    if assignment is None:
        return _blocks.no_seat(label), f"no seat for {label}"
    if assignment.hidden:
        return _blocks.hidden_private(assignment, target_label=label), "occupied (private)"
    return _blocks.occupied(assignment, target_label=label), f"{label} → {assignment.seat_id}"
