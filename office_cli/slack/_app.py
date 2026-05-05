"""``/whereis`` slash-command handler wired onto a slack_bolt App.

The handler is structurally typed: it expects an ``ack`` callable, a
``client`` with ``users_info`` + ``chat_postEphemeral`` methods, and a
``command`` dict. Tests pass a small ``FakeSlackContext`` instead of a
real Bolt app, so this module never needs the SDK at import time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from office_cli._dates import parse_iso_date, today_iso_date
from office_cli._roles import RolesConfig, resolve_roles, role_for_email
from office_cli.cli._errors import EXIT_ENV_ERROR, OfficeError
from office_cli.seats import SeatService
from office_cli.slack import _blocks
from office_cli.slack._resolve import ParsedTarget, parse_target

_AUTO = object()


def build_app(
    service: SeatService,
    *,
    app: Any | None = None,
    roles: Any = None,
    data_dir: Path | None = None,
    command_name: str = "/whereis",
) -> Any:
    """Register the ``/whereis`` listener and return the configured app.

    If ``app`` is ``None`` we construct a default ``slack_bolt.App``
    (which reads ``SLACK_BOT_TOKEN`` from the env). Tests pass a fake
    app exposing only ``.command(name)``.

    ``roles`` is the role-mapping config. ``None`` (the default) keeps
    every caller as ``viewer`` — the Stage 4–6 behavior. Pass an
    explicit :class:`RolesConfig`, or pass ``data_dir`` to auto-resolve
    from ``data/offices.yaml`` (production path used by ``office
    slack-serve``).

    ``command_name`` overrides the slash-command label the listener
    binds to. The default ``/whereis`` matches the project identity;
    operators whose workspace already owns ``/whereis`` (e.g. another
    app) can rebind by setting ``OFFICE_SLACK_COMMAND`` on the
    ``slack-serve`` entry point. Must start with ``/``.
    """
    if not command_name.startswith("/"):
        raise OfficeError(
            code=EXIT_ENV_ERROR,
            message=f"command_name must start with '/': got {command_name!r}",
            remediation="set OFFICE_SLACK_COMMAND=/your-command (leading slash required).",
        )
    if roles is None and data_dir is not None:
        roles = resolve_roles(data_dir)
    if app is None:
        from slack_bolt import App

        app = App()

    @app.command(command_name)
    def _handle_whereis(ack: Callable[[], None], body: dict, command: dict, client: Any) -> None:
        ack()
        text = command.get("text", "")
        target = parse_target(text)
        blocks, label = _resolve_and_lookup(service, client, body, command, target, roles)
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
    roles: RolesConfig | None,
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

    # Resolve the caller's role from their Slack profile email + the roles
    # config. When ``roles`` is None or the caller's email can't be
    # fetched, default to viewer (matches Stage 4–6 behavior).
    role = _resolve_caller_role(client, body, command, roles)

    if target.email:
        email = target.email
        label = email
        return _lookup(service, email, label, as_of=as_of, role=role)

    user_id = target.user_id or command.get("user_id") or body.get("user_id", "")
    if not user_id:
        return _blocks.lookup_failed("no Slack user id supplied"), "no user id"

    email, fail_reason = _email_from_user_id(client, user_id)
    if not email:
        return _blocks.lookup_failed(fail_reason), "lookup failed"
    # When the caller asked about themselves, label as "you"; otherwise
    # use the @-mention so Slack renders the name.
    label = "you" if target.self_lookup else f"<@{user_id}>"
    return _lookup(service, email, label, as_of=as_of, role=role)


def _resolve_caller_role(client: Any, body: dict, command: dict, roles: RolesConfig | None) -> str:
    """Identify the slash-command caller and resolve their role.

    Defaults to viewer when ``roles`` is not configured or when the
    caller's profile email isn't fetchable. The redaction at the service
    layer is keyed on this role.
    """
    if roles is None:
        return "viewer"
    caller_user_id = command.get("user_id") or body.get("user_id", "")
    if not caller_user_id:
        return "viewer"
    email, _reason = _email_from_user_id(client, caller_user_id)
    return role_for_email(roles, email)


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
    role: str | None = None,
) -> tuple[list[dict[str, Any]], str]:
    # Both blocks and the `text` fallback use ``label`` so we never leak
    # the resolved profile email through the screen-reader / older-client
    # rendering path — it would defeat the redaction the blocks rely on.
    assignment = service.whereis(email, as_of=as_of, role=role)
    if assignment is None:
        return _blocks.no_seat(label), f"no seat for {label}"
    # Stage 7: a ``redacted=True`` assignment carries the privacy
    # treatment the service applied for viewer callers. ``hidden`` alone
    # is no longer enough to gate the private block — editors and
    # planning callers see hidden seats with full details.
    if assignment.redacted:
        return _blocks.hidden_private(assignment, target_label=label), "occupied (private)"
    return _blocks.occupied(assignment, target_label=label), f"{label} → {assignment.seat_id}"
