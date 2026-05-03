# Slack `/whereis`

## What it is

A Slack slash command — `/whereis @user`, `/whereis email@domain`,
or just `/whereis` (self-lookup) — that resolves to a seat ID and
floor. Responses are **ephemeral** (only the caller sees them) and
honor every redaction the rest of the system does (hidden seats,
auto-vacate, role gating, effective-date windows).

It runs in **Socket Mode** so you don't need a public HTTPS
endpoint; just the bot + app tokens.

## Why

The Slack call-out is the primary user surface for the v1 product
(per [issue #1](https://github.com/agentculture/office-agent/issues/1)).
"Where is X sitting?" is the most common ask, and it's friction-free
to type into the Slack search bar. Building it as a slash command
instead of a chatbot keeps the surface narrow and the privacy
posture conservative (ephemeral by default).

## Install

```bash
uv tool install 'office-cli[slack]'
```

The package imports without `slack-bolt`; only `office slack-serve`
lazy-imports it.

## Configure

### Slack app side

In your Slack app config (<https://api.slack.com/apps>):

1. **Bot scopes** (OAuth & Permissions):
   - `commands` — to register `/whereis`.
   - `users:read.email` — for `users.info` to return `profile.email`.
   - `chat:write` — to post the ephemeral response.
2. **Slash command** (Slash Commands → Create New Command):
   - Command: `/whereis`.
   - Short description: `Find someone's seat`.
   - Usage hint: `[@user | email@domain]`.
3. **Socket Mode** (Socket Mode → Enable). Generate an
   app-level token with `connections:write` scope.

### Repo side

Two env vars, both secret-grade (never in YAML):

```bash
export SLACK_BOT_TOKEN=xoxb-...   # OAuth → Install App
export SLACK_APP_TOKEN=xapp-...   # Basic Information → App-Level Tokens
```

Optional: for the deep-link button on responses, point at your web
deployment:

```bash
export OFFICE_WEB_BASE_URL=https://office.example.com
```

When set, the Slack response includes an "Open map" button linking
to `${OFFICE_WEB_BASE_URL}/floors/<floor>?seat=<seat>`.

## Use

```bash
office slack-serve                    # blocking listener (Socket Mode)
office slack-serve --bot-token xoxb-... --app-token xapp-...   # explicit override
```

In Slack:

```text
/whereis                                   # self-lookup
/whereis @alice                            # mention
/whereis alice@example.com                 # email
/whereis @alice 2026-07-15                 # as-of trailing date (Stage 6)
/whereis alice@example.com 2026-07-15
/whereis 2026-07-15                        # self-lookup as-of a date
```

## How it works

### Module layout

| File                                      | Role                                                                      |
| ----------------------------------------- | ------------------------------------------------------------------------- |
| `office_cli/cli/_commands/slack_serve.py` | `office slack-serve` verb; reads tokens; constructs the bolt App.         |
| `office_cli/slack/__init__.py`            | Re-exports `build_app`, `run_socket_mode`.                                |
| `office_cli/slack/_app.py`                | `build_app(service, *, app, roles, data_dir)` — registers the listener.   |
| `office_cli/slack/_resolve.py`            | Pure parser for the slash-command argument.                               |
| `office_cli/slack/_blocks.py`             | Block Kit response builders (`occupied`, `no_seat`, `hidden_private`, …). |
| `office_cli/slack/_serve.py`              | `run_socket_mode(app, app_token)` — blocking entry point.                 |

### Argument parsing

`parse_target(text) -> ParsedTarget` (in `_resolve.py`) recognizes:

- `<@U123|alice>` — Slack-encoded mention. Extract user ID; resolve
  to email via `users.info`.
- `alice@x.com` — plain text email; used directly.
- empty / whitespace — `self_lookup=True`; resolve caller's user
  ID via the slash-command body.
- A trailing `YYYY-MM-DD` token on any of the three shapes peels off
  as the as-of date.

ReDoS safety: input over 256 chars short-circuits to a parse
failure; the email regex is split into literal-dot-separated
segments so backtracking stays linear.

### Caller-role resolution

When [SSO + roles](./roles.md) is configured (`data/offices.yaml`
has a `roles:` block), the listener:

1. Calls `users.info` on the caller's `user_id` to get their email.
2. Looks the email up in the `RolesConfig` map → `viewer` /
   `editor` / `planning`.
3. Passes the role into `service.whereis(email, role=...)`.

Hidden seats render as `"occupied (private)"` for viewers;
editors / planning callers see the full block. Without
`roles_cfg`, every caller is treated as `viewer` (matches Stage
4–6 behavior).

### Response shapes

Responses are always ephemeral (`chat.postEphemeral`). The Block
Kit output has four shapes:

| Shape            | Used when                                               |
| ---------------- | ------------------------------------------------------- |
| `parse_failed`   | The text didn't match a mention / email / date.         |
| `lookup_failed`  | `users.info` failed or returned no email.               |
| `no_seat`        | The target has no current assignment (or auto-vacated). |
| `occupied`       | Full details (caller has full-access role).             |
| `hidden_private` | Hidden seat + viewer caller — "occupied (private)".     |

The plain-text fallback (`text=`) uses the same `label` the blocks
use, **never the resolved profile email**. This prevents
older/screen-reader clients from leaking the email when a hidden
block is rendered.

### Deep-link button

When `OFFICE_WEB_BASE_URL` is set, every `occupied` response gets
an "Open map" button pointing at
`${BASE}/floors/<floor>?seat=<seat>`. The web server (Stage 5)
resolves that short URL to the canonical SPA path
`/offices/<office>/floors/<floor>` so callers don't need to know
the office id.

### Acknowledgement contract

`ack()` is called immediately on receipt — Slack requires a 3s
ACK or it retries. The slow work (`users.info`, `service.whereis`)
runs synchronously after `ack()`; for v1's call volume this is
fine.

## Limits + roadmap

- **No threaded responses / canvases** — ephemeral block, plain
  text fallback. Future ergonomics could land in a follow-up
  issue.
- **No bot-message rate limit handling** — relies on Slack's
  ephemeral path which has generous limits; if you hit them,
  open an issue.
- **`OFFICE_WEB_BASE_URL` is global** — multi-office deployments
  point at one web frontend. Per-office routing would need a
  small lookup change.
- **No `/seats` admin verb** — `/whereis` is the only slash
  command; mutations stay on the CLI / Sheets / Dynamo path.

## Related

- [Architecture stages — Stage 4](../architecture.md) — PR-by-PR
  record of the slash command landing.
- [SSO + roles](./roles.md) — caller-email → role mapping.
- [Effective-date windows](./effective-dates.md) — trailing
  `YYYY-MM-DD` token semantics.
- [Web map](./web-map.md) — destination of the deep-link button.
