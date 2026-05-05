"""End-to-end tests for the /whereis slash-command handler.

Exercises the listener against a small ``FakeSlackApp`` so no real
``slack_bolt`` install is required. The same handler logic runs in
production; the only difference is the app object.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from office_cli.people import Employee
from office_cli.people.bamboohr import BambooHRDirectory
from office_cli.seats import build_service
from office_cli.slack import build_app
from tests.test_bamboohr_directory import FakeBambooHRClient


class FakeSlackApp:
    """Captures `app.command(name)`-decorated handlers for direct invocation."""

    def __init__(self) -> None:
        self.handlers: dict[str, Any] = {}

    def command(self, name: str):
        def decorator(fn):
            self.handlers[name] = fn
            return fn

        return decorator


class FakeSlackClient:
    """Stand-in for the real WebClient: records postEphemeral payloads."""

    def __init__(self, users: dict[str, dict[str, Any]] | None = None) -> None:
        self.users = users or {}
        self.posted: list[dict[str, Any]] = []
        self.users_info_error: Exception | None = None

    def users_info(self, *, user: str) -> dict[str, Any]:
        if self.users_info_error is not None:
            raise self.users_info_error
        if user not in self.users:
            return {"user": {"profile": {}}}
        return {"user": self.users[user]}

    def chat_postEphemeral(self, **kwargs: Any) -> None:
        self.posted.append(kwargs)


def _invoke(app, body, command, client) -> None:
    """Call the registered /whereis handler with a no-op ack."""
    app.handlers["/whereis"](ack=lambda: None, body=body, command=command, client=client)


def _service_with_active(data_dir: Path, *active_emails: str):
    employees = [Employee(email=e, name=e.split("@")[0]) for e in active_emails]
    client = FakeBambooHRClient(employees)
    directory = BambooHRDirectory(client, cache_ttl_seconds=99999)
    service = build_service(data_dir)
    service.directory = directory
    return service


def _last_blocks(client: FakeSlackClient) -> list[dict[str, Any]]:
    assert client.posted, "no chat_postEphemeral call recorded"
    return client.posted[-1]["blocks"]


def _block_text(blocks: list[dict[str, Any]]) -> str:
    """Concatenate every section / context text for substring assertions."""
    parts: list[str] = []
    for b in blocks:
        if "text" in b and isinstance(b["text"], dict):
            parts.append(b["text"].get("text", ""))
        for el in b.get("elements", []):
            if isinstance(el, dict):
                inner = el.get("text")
                if isinstance(inner, dict):
                    parts.append(inner.get("text", ""))
                elif isinstance(inner, str):
                    parts.append(inner)
    return "\n".join(parts)


def test_at_mention_renders_seat(data_dir: Path) -> None:
    service = _service_with_active(data_dir, "alice@example.com")
    service.assign("5-T-01", "alice@example.com")
    app = build_app(service, app=FakeSlackApp())
    client = FakeSlackClient(users={"U123": {"profile": {"email": "alice@example.com"}}})
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": "<@U123|alice>"},
        client=client,
    )
    text = _block_text(_last_blocks(client))
    assert "5-T-01" in text
    assert "tlv-floor-5" in text


def test_plain_email_path(data_dir: Path) -> None:
    service = _service_with_active(data_dir, "bob@example.com")
    service.assign("5-T-02", "bob@example.com")
    app = build_app(service, app=FakeSlackApp())
    client = FakeSlackClient()
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": "bob@example.com"},
        client=client,
    )
    assert "5-T-02" in _block_text(_last_blocks(client))


def test_no_arg_resolves_caller(data_dir: Path) -> None:
    """No-arg ``/whereis`` resolves the caller and renders second-person.
    Issue #27: must say ``"you sit"``, not ``"you sits"``."""
    service = _service_with_active(data_dir, "carol@example.com")
    service.assign("5-T-03", "carol@example.com")
    app = build_app(service, app=FakeSlackApp())
    client = FakeSlackClient(users={"U999": {"profile": {"email": "carol@example.com"}}})
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": ""},
        client=client,
    )
    text = _block_text(_last_blocks(client))
    assert "5-T-03" in text
    # Subject is bolded by mrkdwn → ``*you* sit at`` is the rendered string.
    assert "*you* sit at" in text
    assert "*you* sits" not in text


def test_email_path_renders_third_person_sits(data_dir: Path) -> None:
    """Default branch (explicit email) keeps third-person ``"sits"``.
    Guards against the #27 fix accidentally swapping the default verb."""
    service = _service_with_active(data_dir, "carol@example.com")
    service.assign("5-T-03", "carol@example.com")
    app = build_app(service, app=FakeSlackApp())
    client = FakeSlackClient()
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": "carol@example.com"},
        client=client,
    )
    text = _block_text(_last_blocks(client))
    assert "carol@example.com* sits at" in text
    assert "carol@example.com* sit at" not in text


def test_at_mention_path_renders_third_person_sits(data_dir: Path) -> None:
    """At-mention path also stays third-person (``<@U123> sits at ...``)."""
    service = _service_with_active(data_dir, "alice@example.com")
    service.assign("5-T-01", "alice@example.com")
    app = build_app(service, app=FakeSlackApp())
    client = FakeSlackClient(users={"U123": {"profile": {"email": "alice@example.com"}}})
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": "<@U123|alice>"},
        client=client,
    )
    text = _block_text(_last_blocks(client))
    assert "<@U123>* sits at" in text
    assert "you sit" not in text


def test_no_seat_renders_helpful_message(data_dir: Path) -> None:
    service = _service_with_active(data_dir, "ghost@example.com")
    app = build_app(service, app=FakeSlackApp())
    client = FakeSlackClient()
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": "ghost@example.com"},
        client=client,
    )
    text = _block_text(_last_blocks(client))
    assert "No seat assigned" in text
    assert "ghost@example.com" in text


def test_hidden_seat_redacts_email(data_dir: Path) -> None:
    service = _service_with_active(data_dir, "exec@example.com")
    service.assign("5-T-04", "exec@example.com", hidden=True)
    app = build_app(service, app=FakeSlackApp())
    client = FakeSlackClient()
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": "exec@example.com"},
        client=client,
    )
    text = _block_text(_last_blocks(client))
    assert "occupied (private)" in text
    assert "tlv-floor-5" in text
    # The hidden-private response must NOT include the seat ID — only
    # the floor — so the floor map row stays unidentifiable.
    assert "5-T-04" not in text


def test_inactive_directory_email_renders_no_seat(data_dir: Path) -> None:
    """Stage 3 auto-vacate must surface through the Slack handler too.

    Assign an active employee, then mark them inactive in the directory;
    /whereis must report no seat (even though the row is still on disk).
    """
    bamboo_client = FakeBambooHRClient([Employee(email="alice@example.com")])
    directory = BambooHRDirectory(bamboo_client, cache_ttl_seconds=0)
    service = build_service(data_dir)
    service.directory = directory
    service.assign("5-T-01", "alice@example.com")

    bamboo_client.employees = []  # offboarded
    directory.invalidate()  # force fresh fetch on next is_active

    app = build_app(service, app=FakeSlackApp())
    client = FakeSlackClient()
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": "alice@example.com"},
        client=client,
    )
    text = _block_text(_last_blocks(client))
    assert "No seat assigned" in text


def test_unparseable_text(data_dir: Path) -> None:
    """Post-#29: a bare token like ``garbage_no_email_no_mention`` is no
    longer a parse failure — it's captured as ``bare_token`` and looked
    up against the assignment store. With no matching local-part, the
    handler renders the new ``no_match_for_token`` block instead."""
    service = _service_with_active(data_dir)
    app = build_app(service, app=FakeSlackApp())
    client = FakeSlackClient()
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": "garbage_no_email_no_mention"},
        client=client,
    )
    text = _block_text(_last_blocks(client))
    assert "Couldn't find a seat for" in text
    assert "garbage_no_email_no_mention" in text


def test_users_info_failure_renders_lookup_error(data_dir: Path) -> None:
    service = _service_with_active(data_dir)
    app = build_app(service, app=FakeSlackApp())
    client = FakeSlackClient()
    client.users_info_error = ConnectionError("Slack down")
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": "<@U123|alice>"},
        client=client,
    )
    text = _block_text(_last_blocks(client))
    assert "users.info call failed" in text


def test_users_info_missing_email_renders_clear_message(data_dir: Path) -> None:
    service = _service_with_active(data_dir)
    app = build_app(service, app=FakeSlackApp())
    client = FakeSlackClient(users={"U123": {"profile": {}}})
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": "<@U123|alice>"},
        client=client,
    )
    text = _block_text(_last_blocks(client))
    assert "users:read.email" in text  # remediation hint surfaced


def test_no_trailing_date_defaults_to_today_filter(data_dir: Path) -> None:
    """Slack defaults ``as_of`` to today so a future-dated row is hidden."""
    service = _service_with_active(data_dir, "alice@example.com")
    service.assign("5-T-01", "alice@example.com", effective_from="2099-01-01")
    app = build_app(service, app=FakeSlackApp())
    client = FakeSlackClient()
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": "alice@example.com"},
        client=client,
    )
    assert "No seat assigned" in _block_text(_last_blocks(client))


def test_invalid_calendar_date_rejected(data_dir: Path) -> None:
    """Trailing tokens that match the regex but aren't real dates surface as parse failures."""
    service = _service_with_active(data_dir, "alice@example.com")
    app = build_app(service, app=FakeSlackApp())
    client = FakeSlackClient()
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": "alice@example.com 2026-02-30"},
        client=client,
    )
    text = _block_text(_last_blocks(client))
    # parse_failed block surfaces the bad date in the message.
    assert "2026-02-30" in text


def test_editor_caller_sees_hidden_seat_in_full(data_dir: Path) -> None:
    """Stage 7: an editor-role caller via the roles map sees the email."""
    from office_cli._roles import RolesConfig

    service = _service_with_active(data_dir, "exec@example.com", "alice@example.com")
    service.assign("5-T-04", "exec@example.com", hidden=True)
    roles = RolesConfig(editor=frozenset({"alice@example.com"}))
    app = build_app(service, app=FakeSlackApp(), roles=roles)
    # ``alice@example.com`` is the caller (resolved via users.info on U999),
    # asking about the hidden seat.
    client = FakeSlackClient(users={"U999": {"profile": {"email": "alice@example.com"}}})
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": "exec@example.com", "user_id": "U999"},
        client=client,
    )
    text = _block_text(_last_blocks(client))
    # Editor caller — the hidden block path is bypassed; full occupancy details visible.
    assert "exec@example.com" in text


def test_viewer_caller_sees_private_for_mention(data_dir: Path) -> None:
    """A non-editor caller asking about ``@user`` (a mention) sees ``occupied (private)``.

    This is the issue-#11 acceptance shape: the caller types
    ``/whereis @bob``, the handler resolves the mention to bob's email
    via ``users.info``, then redacts in the response because the
    caller's role is viewer. The block-level text uses the mention
    (``<@U…>``) as the label — never bob's email.
    """
    from office_cli._roles import RolesConfig

    service = _service_with_active(data_dir, "exec@example.com")
    service.assign("5-T-04", "exec@example.com", hidden=True)
    # Caller (U999 / bob) is NOT in the editor list → stays viewer.
    # Target (U123 / exec) is the @-mention.
    roles = RolesConfig(editor=frozenset({"hr@example.com"}))
    app = build_app(service, app=FakeSlackApp(), roles=roles)
    client = FakeSlackClient(
        users={
            "U999": {"profile": {"email": "bob@example.com"}},
            "U123": {"profile": {"email": "exec@example.com"}},
        }
    )
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": "<@U123|exec>", "user_id": "U999"},
        client=client,
    )
    text = _block_text(_last_blocks(client))
    assert "occupied (private)" in text
    # The mention label was used in the response, not the resolved email.
    assert "exec@example.com" not in text
    assert "<@U123>" in text


def test_trailing_date_filters_via_as_of(data_dir: Path) -> None:
    """Stage 6 — trailing ``YYYY-MM-DD`` token filters via the effective window."""
    service = _service_with_active(data_dir, "alice@example.com")
    service.assign("5-T-01", "alice@example.com", effective_from="2026-07-01")
    app = build_app(service, app=FakeSlackApp())

    # Before the window — handler should report "no seat".
    client_pre = FakeSlackClient()
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": "alice@example.com 2026-06-30"},
        client=client_pre,
    )
    assert "No seat assigned" in _block_text(_last_blocks(client_pre))

    # Inside the window — the seat should appear.
    client_post = FakeSlackClient()
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": "alice@example.com 2026-07-15"},
        client=client_post,
    )
    text = _block_text(_last_blocks(client_post))
    assert "5-T-01" in text


def test_deep_link_button_when_base_url_set(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OFFICE_WEB_BASE_URL", "https://office.example.com")
    service = _service_with_active(data_dir, "alice@example.com")
    service.assign("5-T-01", "alice@example.com")
    app = build_app(service, app=FakeSlackApp())
    client = FakeSlackClient()
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": "alice@example.com"},
        client=client,
    )
    blocks = _last_blocks(client)
    actions = [b for b in blocks if b.get("type") == "actions"]
    assert actions, "expected an actions block with the deep-link button"
    button = actions[0]["elements"][0]
    assert button["url"].startswith("https://office.example.com/")
    assert "5-T-01" in button["url"]


def test_text_fallback_does_not_leak_email_for_mention(data_dir: Path) -> None:
    """Qodo Q2: the `text` fallback must not expose the resolved profile
    email when the caller used an @mention. Otherwise screen-readers or
    older clients see what the blocks deliberately redacted."""
    service = _service_with_active(data_dir, "alice@example.com")
    # No seat assigned for alice — exercises the no-seat branch where
    # the leak was found.
    app = build_app(service, app=FakeSlackApp())
    client = FakeSlackClient(users={"U123": {"profile": {"email": "alice@example.com"}}})
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"channel_id": "C1", "user_id": "U999", "text": "<@U123|alice>"},
        client=client,
    )
    posted = client.posted[-1]
    assert "alice@example.com" not in posted["text"]
    assert "<@U123>" in posted["text"]


def test_command_payload_takes_precedence_for_channel_user(data_dir: Path) -> None:
    """Copilot C2: prefer command[channel_id]/user_id; fall back to body."""
    service = _service_with_active(data_dir, "alice@example.com")
    service.assign("5-T-01", "alice@example.com")
    app = build_app(service, app=FakeSlackApp())
    client = FakeSlackClient()
    _invoke(
        app,
        body={"channel_id": "C-from-body", "user_id": "U-from-body"},
        command={
            "channel_id": "C-from-command",
            "user_id": "U-from-command",
            "text": "alice@example.com",
        },
        client=client,
    )
    assert client.posted[-1]["channel"] == "C-from-command"
    assert client.posted[-1]["user"] == "U-from-command"


def test_text_fallback_in_postephemeral(data_dir: Path) -> None:
    """The handler always passes a `text` fallback so screen readers and
    older clients render something even when blocks are dropped."""
    service = _service_with_active(data_dir, "alice@example.com")
    service.assign("5-T-01", "alice@example.com")
    app = build_app(service, app=FakeSlackApp())
    client = FakeSlackClient()
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": "alice@example.com"},
        client=client,
    )
    assert "text" in client.posted[0]
    assert client.posted[0]["text"]


def test_payload_is_json_serializable(data_dir: Path) -> None:
    """Block Kit payloads must round-trip through JSON; assert no
    accidentally-non-serializable values (e.g. dataclass instances) leak."""
    service = _service_with_active(data_dir, "alice@example.com")
    service.assign("5-T-01", "alice@example.com")
    app = build_app(service, app=FakeSlackApp())
    client = FakeSlackClient()
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": "alice@example.com"},
        client=client,
    )
    json.dumps(client.posted[0]["blocks"])


def test_command_name_override_binds_alternate_slash_command(data_dir: Path) -> None:
    """Operators whose workspace already owns ``/whereis`` can rebind the
    listener via ``command_name`` (set from ``OFFICE_SLACK_COMMAND`` in the
    ``slack-serve`` entry point)."""
    service = _service_with_active(data_dir, "alice@example.com")
    service.assign("5-T-01", "alice@example.com")
    fake_app = FakeSlackApp()
    build_app(service, app=fake_app, command_name="/ai")

    assert "/ai" in fake_app.handlers
    assert "/whereis" not in fake_app.handlers

    client = FakeSlackClient()
    fake_app.handlers["/ai"](
        ack=lambda: None,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": "alice@example.com"},
        client=client,
    )
    assert "5-T-01" in _block_text(_last_blocks(client))


def test_command_name_without_leading_slash_raises(data_dir: Path) -> None:
    service = _service_with_active(data_dir, "alice@example.com")
    from office_cli.cli._errors import OfficeError

    with pytest.raises(OfficeError) as excinfo:
        build_app(service, app=FakeSlackApp(), command_name="ai")
    assert "must start with '/'" in str(excinfo.value)


def test_command_name_with_surrounding_whitespace_is_normalized(data_dir: Path) -> None:
    """Programmatic callers that pass an untrimmed ``command_name`` (e.g. an
    env-var read elsewhere) shouldn't end up registering a handler under
    ``"  /ai  "``. ``build_app`` normalizes at the boundary so every caller
    behaves consistently."""
    service = _service_with_active(data_dir, "alice@example.com")
    fake_app = FakeSlackApp()
    build_app(service, app=fake_app, command_name="  /ai  ")

    assert "/ai" in fake_app.handlers
    assert "  /ai  " not in fake_app.handlers


def test_command_name_empty_after_strip_raises(data_dir: Path) -> None:
    """Whitespace-only ``command_name`` collapses to empty after strip and
    must fail loudly rather than registering a handler under ``""``."""
    service = _service_with_active(data_dir, "alice@example.com")
    from office_cli.cli._errors import OfficeError

    with pytest.raises(OfficeError):
        build_app(service, app=FakeSlackApp(), command_name="   ")


def test_bare_token_resolves_to_assignment(data_dir: Path) -> None:
    """#29 MVP: ``/whereis ori.nachum`` resolves via local-part match."""
    service = _service_with_active(data_dir, "ori.nachum@tipalti.com")
    service.assign("5-T-03", "ori.nachum@tipalti.com")
    app = build_app(service, app=FakeSlackApp())
    client = FakeSlackClient()
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": "ori.nachum"},
        client=client,
    )
    text = _block_text(_last_blocks(client))
    assert "5-T-03" in text
    assert "ori.nachum@tipalti.com" in text


def test_at_username_resolves_to_assignment(data_dir: Path) -> None:
    """Failed-autocomplete (`@username` instead of `<@Uxxx>` markup)
    should be treated as a bare token after the leading ``@`` is
    stripped."""
    service = _service_with_active(data_dir, "ori.nachum@tipalti.com")
    service.assign("5-T-03", "ori.nachum@tipalti.com")
    app = build_app(service, app=FakeSlackApp())
    client = FakeSlackClient()
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": "@ori.nachum"},
        client=client,
    )
    text = _block_text(_last_blocks(client))
    assert "5-T-03" in text


def test_bare_token_no_match_renders_helpful_error(data_dir: Path) -> None:
    """Unknown bare token renders the new ``no_match_for_token`` block
    with guidance on what is accepted."""
    service = _service_with_active(data_dir)
    app = build_app(service, app=FakeSlackApp())
    client = FakeSlackClient()
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": "ghost"},
        client=client,
    )
    text = _block_text(_last_blocks(client))
    assert "Couldn't find a seat for `ghost`" in text
    assert "email" in text.lower() or "@mention" in text


def test_bare_token_disambiguation_renders_candidates(data_dir: Path) -> None:
    """Two assignments sharing a local-part across domains → the multi-
    section disambiguation block lists both and ends with the
    "re-run with the full email" hint."""
    service = _service_with_active(data_dir, "alice@x.com", "alice@y.com")
    service.assign("5-T-01", "alice@x.com")
    service.assign("5-T-02", "alice@y.com")
    app = build_app(service, app=FakeSlackApp())
    client = FakeSlackClient()
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": "alice"},
        client=client,
    )
    text = _block_text(_last_blocks(client))
    assert "Multiple seats matched" in text
    assert "alice@x.com" in text
    assert "alice@y.com" in text
    assert "5-T-01" in text
    assert "5-T-02" in text
    assert "Re-run with the full email" in text


def test_bare_token_with_mrkdwn_metachars_is_escaped(data_dir: Path) -> None:
    """PR #40 review (Copilot): a bare token containing ``<``/``>`` /
    ``&`` / backtick must not break formatting or inject Slack control
    sequences (``<!here>``, ``<@U…>``) when echoed back. The block
    builders escape these before mrkdwn display, and the ``text``
    fallback stays free of the token entirely."""
    service = _service_with_active(data_dir)
    app = build_app(service, app=FakeSlackApp())
    client = FakeSlackClient()
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": "<!here>"},
        client=client,
    )
    posted = client.posted[-1]
    blocks_text = _block_text(posted["blocks"])
    # The literal ``<!here>`` must be escaped, not pinged.
    assert "<!here>" not in blocks_text
    assert "&lt;!here&gt;" in blocks_text
    # And the ``text`` fallback (rendered when blocks aren't supported)
    # must not echo the token at all.
    assert "<!here>" not in posted["text"]


def test_bare_token_text_fallback_does_not_leak_token(data_dir: Path) -> None:
    """Companion to the mrkdwn-escape test: even a benign token shouldn't
    appear in the ``text`` fallback, because Slack parses that string
    too. We assert the no-match path's fallback is the documented
    constant, not an interpolation of the user input."""
    service = _service_with_active(data_dir)
    app = build_app(service, app=FakeSlackApp())
    client = FakeSlackClient()
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": "ghost"},
        client=client,
    )
    assert client.posted[-1]["text"] == "no seat found for that name"


def test_slack_directory_resolves_single_match_to_seat(data_dir: Path) -> None:
    """#38: when local-part match misses, fall through to a Slack
    workspace name match. One match → use the candidate's email →
    standard seat-found render via ``_lookup``.
    """
    from office_cli.slack._directory import SlackUser, SlackUserDirectory

    service = _service_with_active(data_dir, "alice@example.com")
    service.assign("5-T-01", "alice@example.com")

    class StaticDirectory(SlackUserDirectory):
        def __init__(self, users: list[SlackUser]) -> None:
            self._users_static = users
            self._enabled = True

        def find_by_name(self, token: str) -> list[SlackUser]:  # type: ignore[override]
            return [u for u in self._users_static if u.matches(token)]

    directory = StaticDirectory(
        [
            SlackUser(
                user_id="U_ALICE",
                display_name="Alice",
                real_name="Alice Smith",
                name="alice",
                email="alice@example.com",
            )
        ]
    )
    app = build_app(service, app=FakeSlackApp(), slack_directory=directory)
    client = FakeSlackClient()
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": "Alice"},  # display name, not the local-part
        client=client,
    )
    text = _block_text(_last_blocks(client))
    assert "5-T-01" in text
    assert "alice@example.com" in text


def test_slack_directory_disambiguation_for_multiple_matches(data_dir: Path) -> None:
    """≥2 Slack users sharing the matched name render the new
    ``disambiguation_users`` block (display name + email per
    candidate, no seat info)."""
    from office_cli.slack._directory import SlackUser, SlackUserDirectory

    service = _service_with_active(data_dir, "alice.x@x.com", "alice.y@y.com")

    class StaticDirectory(SlackUserDirectory):
        def __init__(self, users: list[SlackUser]) -> None:
            self._users_static = users
            self._enabled = True

        def find_by_name(self, token: str) -> list[SlackUser]:  # type: ignore[override]
            return [u for u in self._users_static if u.matches(token)]

    directory = StaticDirectory(
        [
            SlackUser(
                user_id="U_ALICE_X",
                display_name="Alice",
                real_name="Alice X",
                name="alice.x",
                email="alice.x@x.com",
            ),
            SlackUser(
                user_id="U_ALICE_Y",
                display_name="Alice",
                real_name="Alice Y",
                name="alice.y",
                email="alice.y@y.com",
            ),
        ]
    )
    app = build_app(service, app=FakeSlackApp(), slack_directory=directory)
    client = FakeSlackClient()
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": "Alice"},
        client=client,
    )
    text = _block_text(_last_blocks(client))
    assert "Multiple Slack users matched" in text
    assert "alice.x@x.com" in text
    assert "alice.y@y.com" in text
    assert "Re-run with the full email" in text


def test_disabled_slack_directory_keeps_legacy_no_match_path(data_dir: Path) -> None:
    """``SlackUserDirectory(enabled=False)`` short-circuits the new
    fallback — the caller sees the same ``no_match_for_token`` block
    they'd get without #38."""
    from office_cli.slack._directory import SlackUserDirectory

    service = _service_with_active(data_dir)
    directory = SlackUserDirectory(client=None, enabled=False)
    app = build_app(service, app=FakeSlackApp(), slack_directory=directory)
    client = FakeSlackClient()
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": "ghost"},
        client=client,
    )
    text = _block_text(_last_blocks(client))
    assert "Couldn't find a seat for `ghost`" in text


def test_disambiguation_users_caps_render_with_overflow_hint(data_dir: Path) -> None:
    """PR #41 review (Copilot): Slack messages cap at 50 blocks; a
    common name in a large workspace can match dozens of users. The
    builder must render at most ``_DISAMBIG_CANDIDATE_LIMIT``
    candidates and add a context block reporting the rest, so
    ``chat.postEphemeral`` doesn't reject the payload silently."""
    from office_cli.slack._blocks import _DISAMBIG_CANDIDATE_LIMIT, disambiguation_users
    from office_cli.slack._directory import SlackUser

    candidates = [
        SlackUser(
            user_id=f"U_{i}",
            display_name=f"Alex {i}",
            real_name=f"Alex {i}",
            name=f"alex.{i}",
            email=f"alex.{i}@example.com",
        )
        for i in range(25)
    ]
    blocks = disambiguation_users("alex", candidates)

    # Header + at-most-cap sections + overflow context + final hint.
    section_blocks = [b for b in blocks if b.get("type") == "section"]
    assert len(section_blocks) == 1 + _DISAMBIG_CANDIDATE_LIMIT  # header + capped list

    # Overflow context block reports the remainder.
    text = _block_text(blocks)
    overflow = 25 - _DISAMBIG_CANDIDATE_LIMIT
    assert f"…and {overflow} more" in text
    assert "Re-run with the full email" in text

    # Total payload stays well under Slack's 50-block ceiling.
    assert len(blocks) < 50


def test_disambiguation_users_no_overflow_hint_when_under_cap(data_dir: Path) -> None:
    """When candidate count is at or below the cap, no overflow context
    block is added — only the standard "re-run with full email" hint."""
    from office_cli.slack._blocks import disambiguation_users
    from office_cli.slack._directory import SlackUser

    candidates = [
        SlackUser(
            user_id="U_A",
            display_name="Alice",
            real_name="Alice A",
            name="alice.a",
            email="alice.a@example.com",
        ),
        SlackUser(
            user_id="U_B",
            display_name="Alice",
            real_name="Alice B",
            name="alice.b",
            email="alice.b@example.com",
        ),
    ]
    blocks = disambiguation_users("Alice", candidates)
    text = _block_text(blocks)
    assert "more — refine" not in text
    assert "Re-run with the full email" in text


def test_local_part_wins_before_slack_directory(data_dir: Path) -> None:
    """The Slack directory is consulted only when the local-part path
    misses; an existing assignment short-circuits the API call."""
    from office_cli.slack._directory import SlackUserDirectory

    service = _service_with_active(data_dir, "ori.nachum@tipalti.com")
    service.assign("5-T-03", "ori.nachum@tipalti.com")

    class CountingDirectory(SlackUserDirectory):
        def __init__(self) -> None:
            self.calls = 0
            self._enabled = True

        def find_by_name(self, token: str):  # type: ignore[override]
            self.calls += 1
            return []

    directory = CountingDirectory()
    app = build_app(service, app=FakeSlackApp(), slack_directory=directory)
    client = FakeSlackClient()
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": "ori.nachum"},
        client=client,
    )
    assert directory.calls == 0
    assert "5-T-03" in _block_text(_last_blocks(client))


def test_bare_token_disambiguation_redacts_hidden_seat_id(data_dir: Path) -> None:
    """PR #40 review (Qodo): when the disambiguation list includes a
    redacted (hidden) entry, it must omit the ``seat_id`` to match
    ``hidden_private``'s privacy contract — viewer-role callers can
    see *that* there's a private match without learning where it sits."""
    from office_cli._roles import RolesConfig

    service = _service_with_active(data_dir, "alice@x.com", "alice@y.com")
    service.assign("5-T-01", "alice@x.com")  # public
    service.assign("5-T-02", "alice@y.com", hidden=True)  # private
    # Empty roles config → caller is viewer → redaction fires for hidden seats.
    roles = RolesConfig()
    app = build_app(service, app=FakeSlackApp(), roles=roles)
    # The caller's user_id maps to no role entry → defaults to viewer.
    client = FakeSlackClient(users={"U999": {"profile": {"email": "viewer@x.com"}}})
    _invoke(
        app,
        body={"channel_id": "C1", "user_id": "U999"},
        command={"text": "alice"},
        client=client,
    )
    text = _block_text(_last_blocks(client))
    # Public match is fully visible.
    assert "5-T-01" in text
    assert "alice@x.com" in text
    # Hidden match: floor visible, seat_id NOT, email NOT.
    assert "tlv-floor-5" in text
    assert "5-T-02" not in text
    assert "alice@y.com" not in text
    assert "occupied (private)" in text
