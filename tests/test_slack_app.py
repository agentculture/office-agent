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
    assert "5-T-03" in _block_text(_last_blocks(client))


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
    assert "Couldn't parse" in text
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
