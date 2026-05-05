"""``/whereis`` slash-command handler wired onto a slack_bolt App.

The handler is structurally typed: it expects an ``ack`` callable, a
``client`` with ``users_info`` + ``chat_postEphemeral`` methods, and a
``command`` dict. Tests pass a small ``FakeSlackContext`` instead of a
real Bolt app, so this module never needs the SDK at import time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable

from office_cli._dates import is_effective, parse_iso_date, today_iso_date
from office_cli._roles import RolesConfig, is_full_access, resolve_roles, role_for_email
from office_cli.cli._errors import EXIT_ENV_ERROR, OfficeError
from office_cli.seats import SeatService
from office_cli.slack import _blocks
from office_cli.slack._directory import SlackUserDirectory
from office_cli.slack._fuzzy import (
    DEFAULT_AUTO_PICK_GAP,
    DEFAULT_CUTOFF,
    DEFAULT_LIMIT,
    auto_pick,
    rank_candidates,
)
from office_cli.slack._resolve import ParsedTarget, parse_target

_AUTO = object()


def build_app(
    service: SeatService,
    *,
    app: Any | None = None,
    roles: Any = None,
    data_dir: Path | None = None,
    slack_directory: SlackUserDirectory | None = None,
    fuzzy_cutoff: float = DEFAULT_CUTOFF,
    fuzzy_limit: int = DEFAULT_LIMIT,
    fuzzy_gap: float = DEFAULT_AUTO_PICK_GAP,
    command_name: str = "/whereis",
) -> Any:
    """Register the configured slash-command listener and return the app.

    The listener binds to ``command_name`` (default ``/whereis``); see
    the parameter notes below for how operators rebind it.

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
    ``slack-serve`` entry point. Surrounding whitespace is stripped;
    the resulting value must be non-empty and start with ``/``.

    ``slack_directory`` (#38) is an optional :class:`SlackUserDirectory`
    consulted when the bare-token MVP from #29 returns no local-part
    match. ``None`` (the default) keeps the local-part-only behavior;
    pass an instance to enable name → email resolution against the
    Slack workspace roster. The slack-serve entry point constructs one
    by default and respects ``OFFICE_SLACK_DIRECTORY=disabled``.

    ``fuzzy_cutoff`` / ``fuzzy_limit`` / ``fuzzy_gap`` (#39) tune the
    final tier of the resolution chain: difflib-backed fuzzy matching
    against the union of assignment-store local-parts and Slack
    roster names, with auto-pick when the top candidate clears the
    runner-up by ``fuzzy_gap`` and an interactive disambiguation list
    otherwise. Defaults match :mod:`office_cli.slack._fuzzy`; the
    slack-serve entry point exposes ``OFFICE_FUZZY_CUTOFF`` and
    ``OFFICE_FUZZY_LIMIT`` env overrides.
    """
    command_name = command_name.strip()
    if not command_name or not command_name.startswith("/"):
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
        blocks, label = _resolve_and_lookup(
            service,
            client,
            body,
            command,
            target,
            roles,
            slack_directory,
            fuzzy_cutoff=fuzzy_cutoff,
            fuzzy_limit=fuzzy_limit,
            fuzzy_gap=fuzzy_gap,
        )
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

    # #39: handle the "This person" button on a fuzzy disambiguation
    # message. The button's ``value`` carries a JSON payload
    # ``{"email": ..., "as_of": ...}`` so we can re-run the seat
    # lookup against the *same* as-of window the picker was
    # generated for (#42 review fix). ``respond`` is Bolt's
    # ``response_url`` shortcut; tests pass a recorder.
    @app.action(_blocks.DISAMBIG_FUZZY_ACTION_ID)
    def _handle_pick(
        ack: Callable[[], None],
        body: dict,
        respond: Callable[[dict], None],
        client: Any,
    ) -> None:
        ack()
        actions = body.get("actions") or []
        raw_value = actions[0].get("value", "") if actions else ""
        email, encoded_as_of = _blocks.decode_pick_value(raw_value)
        if not email:
            respond(
                {
                    "replace_original": True,
                    "text": "couldn't read the picked candidate",
                }
            )
            return
        # Same role gate the slash command applies — pick + lookup
        # must use the *caller's* role, not the original ephemeral's.
        # ``body`` for action callbacks carries ``user.id``; mirror the
        # slash-command shape (``user_id``) so ``_resolve_caller_role``
        # can read it the same way.
        synthetic_command = {"user_id": (body.get("user") or {}).get("id", "")}
        role = _resolve_caller_role(client, body, synthetic_command, roles)
        # Honor the encoded ``as_of`` if present; otherwise default to
        # today (no_arg slash command path) so the click never resolves
        # against an empty / past-window state by accident.
        as_of = encoded_as_of or today_iso_date(service._clock)
        blocks, label = _lookup(service, email, label=email, as_of=as_of, role=role)
        respond({"replace_original": True, "blocks": blocks, "text": label})

    return app


def _resolve_and_lookup(
    service: SeatService,
    client: Any,
    body: dict,
    command: dict,
    target: ParsedTarget,
    roles: RolesConfig | None,
    slack_directory: SlackUserDirectory | None = None,
    *,
    fuzzy_cutoff: float = DEFAULT_CUTOFF,
    fuzzy_limit: int = DEFAULT_LIMIT,
    fuzzy_gap: float = DEFAULT_AUTO_PICK_GAP,
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

    if target.bare_token:
        return _lookup_by_local_part(
            service,
            target.bare_token,
            as_of=as_of,
            role=role,
            slack_directory=slack_directory,
            fuzzy_cutoff=fuzzy_cutoff,
            fuzzy_limit=fuzzy_limit,
            fuzzy_gap=fuzzy_gap,
        )

    user_id = target.user_id or command.get("user_id") or body.get("user_id", "")
    if not user_id:
        return _blocks.lookup_failed("no Slack user id supplied"), "no user id"

    email, fail_reason = _email_from_user_id(client, user_id)
    if not email:
        return _blocks.lookup_failed(fail_reason), "lookup failed"
    # When the caller asked about themselves, label as "you" and pick the
    # second-person verb form ("you sit"); otherwise use the @-mention so
    # Slack renders the name and stay third-person ("<@U…> sits").
    label = "you" if target.self_lookup else f"<@{user_id}>"
    verb = "sit" if target.self_lookup else "sits"
    return _lookup(service, email, label, as_of=as_of, role=role, verb=verb)


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


def _lookup_by_local_part(
    service: SeatService,
    token: str,
    *,
    as_of: str | None = None,
    role: str | None = None,
    slack_directory: SlackUserDirectory | None = None,
    fuzzy_cutoff: float = DEFAULT_CUTOFF,
    fuzzy_limit: int = DEFAULT_LIMIT,
    fuzzy_gap: float = DEFAULT_AUTO_PICK_GAP,
) -> tuple[list[dict[str, Any]], str]:
    """#29 MVP + #38: ``/whereis ori.nachum`` resolves via the
    assignment store's email local-parts; if no local-part hits and a
    Slack directory is configured, fall through to a name lookup
    against the workspace roster.

    ``text`` fallback strings stay free of ``token``: Slack parses the
    fallback for ``<!here>`` / ``<@U…>`` / ``<#C…>`` sequences when
    blocks aren't rendered, so an attacker-controlled token must not
    land there. The block builders escape the token for mrkdwn
    display; the fallback uses constants.
    """
    matches = service.find_by_local_part(token, as_of=as_of, role=role)
    if not matches:
        # #38: try the Slack workspace roster for a name match.
        return _lookup_by_slack_directory(
            service,
            token,
            slack_directory,
            as_of=as_of,
            role=role,
            fuzzy_cutoff=fuzzy_cutoff,
            fuzzy_limit=fuzzy_limit,
            fuzzy_gap=fuzzy_gap,
        )
    if len(matches) == 1:
        a = matches[0]
        # Use the resolved (store-derived) email as the label so even
        # the single-match path doesn't echo the user's raw token.
        label = a.employee_email or "(redacted)"
        if a.redacted:
            return _blocks.hidden_private(a, target_label=label), "occupied (private)"
        return (
            _blocks.occupied(a, target_label=label),
            f"{label} → {a.seat_id}",
        )
    return _blocks.disambiguation(token, matches), f"{len(matches)} matches"


def _lookup_by_slack_directory(
    service: SeatService,
    token: str,
    slack_directory: SlackUserDirectory | None,
    *,
    as_of: str | None,
    role: str | None,
    fuzzy_cutoff: float = DEFAULT_CUTOFF,
    fuzzy_limit: int = DEFAULT_LIMIT,
    fuzzy_gap: float = DEFAULT_AUTO_PICK_GAP,
) -> tuple[list[dict[str, Any]], str]:
    """#38: name-match against the Slack workspace roster, with the
    directory's TTL cache. Falls through to the #39 fuzzy resolver
    when no exact name matches.
    """
    candidates = slack_directory.find_by_name(token) if slack_directory else []
    if len(candidates) == 1:
        return _lookup(
            service,
            email=candidates[0].email,
            label=candidates[0].email,
            as_of=as_of,
            role=role,
        )
    if len(candidates) > 1:
        return (
            _blocks.disambiguation_users(token, candidates),
            f"{len(candidates)} matches",
        )
    # Empty roster match → final tier: fuzzy across local-parts ∪ roster.
    return _lookup_by_fuzzy(
        service,
        token,
        slack_directory,
        as_of=as_of,
        role=role,
        cutoff=fuzzy_cutoff,
        limit=fuzzy_limit,
        gap=fuzzy_gap,
    )


def _lookup_by_fuzzy(
    service: SeatService,
    token: str,
    slack_directory: SlackUserDirectory | None,
    *,
    as_of: str | None,
    role: str | None,
    cutoff: float,
    limit: int,
    gap: float,
) -> tuple[list[dict[str, Any]], str]:
    """#39: third tier of the resolution chain — fuzzy match against
    the union of assignment-store local-parts and Slack roster names.

    Auto-picks when one candidate clearly wins (top score exceeds the
    runner-up by ``gap``); otherwise renders the interactive
    ``disambiguation_fuzzy`` picker. The picker's button click is
    handled by the ``whereis_pick`` action handler registered in
    :func:`build_app`, which re-runs the seat lookup against the
    chosen email.
    """
    pool = list(_build_fuzzy_pool(service, slack_directory, as_of=as_of, role=role))
    # Rank the FULL pool (no ``limit + 1`` cap) so:
    #   * ``auto_pick`` sees the true runner-up — capping at
    #     ``limit + 1`` would let ``fuzzy_limit=1`` auto-pick even
    #     when many other candidates are within the gap.
    #   * the overflow count reflects every above-cutoff hit, not
    #     just one beyond the render slice.
    # The cutoff already filters useless candidates, so a ranked
    # list at v1 scale stays small.
    ranked = rank_candidates(token, pool, cutoff=cutoff, limit=len(pool) or 1)
    if not ranked:
        return _blocks.no_match_for_token(token), "no seat found for that name"
    picked = auto_pick(ranked, gap=gap)
    if picked is not None:
        return _lookup(
            service,
            email=picked.email,
            label=picked.email,
            as_of=as_of,
            role=role,
        )
    rendered = ranked[:limit]
    overflow = max(0, len(ranked) - limit)
    return (
        _blocks.disambiguation_fuzzy(token, rendered, overflow=overflow, as_of=as_of),
        f"{len(rendered)} matches",
    )


def _build_fuzzy_pool(
    service: SeatService,
    slack_directory: SlackUserDirectory | None,
    *,
    as_of: str | None,
    role: str | None,
) -> Iterable[tuple[str, str]]:
    """Yield ``(label, email)`` candidates for the fuzzy ranker, with
    the same eligibility rules ``SeatService.find_by_local_part`` /
    ``whereis`` apply.

    For each assignment in the store:

    * non-empty email; otherwise skip (no useful resolution target).
    * for non-full-access (viewer) roles: skip ``hidden=True`` rows
      entirely. The privacy contract behind ``hidden_private`` is
      "viewers don't learn where this person sits"; surfacing the
      email in the disambiguation list — even with the seat
      redacted post-pick — defeats the gate. Track these emails in
      ``excluded`` so the Slack-roster contribution can drop them
      too (a hidden-seat occupant who shows up under their Slack
      display name would otherwise route around the local-part skip).
    * directory ``is_active`` filter: an offboarded employee's row
      shouldn't surface as a fuzzy hit.
    * ``as_of`` window: same gate ``whereis`` enforces.

    For the Slack roster contribution: include every cached user
    whose email isn't in ``excluded``. We don't apply
    ``directory.is_active`` here because it's a different identity
    space (Slack workspace, not BambooHR), and ``_lookup`` post-pick
    will still apply the gate via ``service.whereis``.

    Order matters for ``rank_candidates``'s "first occurrence wins on
    tie" rule: emit local-parts first (the strong source — these
    are people we can definitely seat) then the Slack roster.
    """
    excluded: set[str] = set()
    yield from _yield_eligible_local_parts(
        service, as_of=as_of, full_access=is_full_access(role), excluded=excluded
    )
    yield from _yield_eligible_roster(slack_directory, excluded=excluded)


def _yield_eligible_local_parts(
    service: SeatService,
    *,
    as_of: str | None,
    full_access: bool,
    excluded: set[str],
) -> Iterable[tuple[str, str]]:
    """Local-part contribution to the fuzzy pool. Mutates ``excluded``
    so the roster contribution can drop the same hidden-seat
    occupants if their display name matches."""
    for a in service.store.list():
        email = (a.employee_email or "").strip()
        if not email or "@" not in email:
            continue
        if not full_access and a.hidden:
            excluded.add(email.lower())
            continue
        if not service.directory.is_active(email):
            continue
        if as_of is not None and not is_effective(a, as_of):
            continue
        yield (email.split("@", 1)[0], email)


def _yield_eligible_roster(
    slack_directory: SlackUserDirectory | None,
    *,
    excluded: set[str],
) -> Iterable[tuple[str, str]]:
    """Slack-roster contribution. Drops users whose email is in
    ``excluded`` (the hidden-seat-for-viewer gate from the local-part
    pass)."""
    if slack_directory is None or not slack_directory.enabled:
        return
    for u in slack_directory.iter_users():
        if not u.email or u.email.lower() in excluded:
            continue
        label = u.display_name or u.real_name or u.name or ""
        if label:
            yield (label, u.email)


def _lookup(
    service: SeatService,
    email: str,
    label: str,
    *,
    as_of: str | None = None,
    role: str | None = None,
    verb: str = "sits",
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
    return (
        _blocks.occupied(assignment, target_label=label, verb=verb),
        f"{label} → {assignment.seat_id}",
    )
