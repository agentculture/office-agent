# SSO + roles (viewer / editor / planning)

## What it is

Three roles drive **what callers see** on the web and Slack
surfaces:

- **viewer** (default, everyone) — `hidden=TRUE` seats render as
  `"occupied (private)"`. No email, no notes.
- **editor** (HR / IT) — full details on hidden seats.
- **planning** (facilities) — same as editor in v1; the
  draft-SVG and future-dated visibility carve-outs from issue #1
  are deferred.

The web layer adds OIDC authentication on top — unauthenticated
browsers are redirected through the IdP and back. The CLI is
**operator-only and unrestricted** (no role flag, full data).

## Why

`hidden=TRUE` exists for a reason — exec seats, sensitive HR
moves, etc. Stages 4 + 5 redacted hidden seats for everyone;
Stage 7 lifted the redaction for the small subset of users who
need it (HR / facilities), without complicating the model. The
role check is the **only** gate; the data model carries the same
`hidden` flag everywhere, and the per-role view is computed at
surface time.

OIDC instead of role-passing-by-header because the web is
operator-facing — anyone with a browser tab is a potential
caller. Without auth, `X-Test-Role: editor` would let any visitor
see exec emails. With OIDC, the session is the sole source of
identity in production.

## Install

```bash
pip install office-cli[web,sso]
```

Pulls `authlib`, `itsdangerous`, `httpx` (alongside the `[web]`
extras `fastapi` + `uvicorn`).

## Configure

### IdP (you, in the IdP console)

Set up an OIDC client in your IdP:

- **Authorized redirect URI**:
  `https://<your-host>/auth/callback`
- **Scopes**: `openid email profile`.

Capture the client ID, client secret, and the issuer URL (the IdP
publishes `<issuer>/.well-known/openid-configuration`).

### App-side env

```bash
export OIDC_ISSUER=https://your-idp.example.com
export OIDC_CLIENT_ID=office-agent
export OIDC_CLIENT_SECRET=...
export OIDC_REDIRECT_URL=https://office.example.com/auth/callback
export SESSION_SECRET=$(openssl rand -hex 32)
office serve --port 8000
```

All five env vars must be set together. Setting some-but-not-all
raises `OfficeError(EXIT_ENV_ERROR)` so a partial misconfig fails
fast.

`SESSION_SECRET` should be 32+ bytes. Rotate it per deployment
generation; rotation invalidates all live sessions.

### Optional: HTTP staging behind a TLS proxy

```bash
export OIDC_COOKIE_SECURE=false
```

Defaults to `true` (production-secure). Set to `false` when the
edge is HTTPS but the office-cli process speaks HTTP behind the
proxy — otherwise the browser drops the `Secure` cookie and you
get a login loop.

### Roles map

`data/offices.yaml`:

```yaml
roles:
  editor:
    - "hr-it@tipalti.com"
    - "alice@tipalti.com"
  planning:
    - "facilities@tipalti.com"
```

Anything not listed is `viewer` (the default). Email matching is
case-insensitive; the parser normalizes to lowercase at load time.

## Use

### Web

Visit any URL under `/offices/<id>/floors/<id>` while
unauthenticated → 302 to `/auth/login?next=<original URL>`. The
IdP authenticates → callback at `/auth/callback` → session cookie
set → redirect to original URL. The SPA shell renders, calls
`/api/floors/<id>`, and the response carries the user identity and
a logout button:

```jsonc
{
  "floor": { ... },
  "seats": [ ... ],
  "user": { "email": "alice@tipalti.com", "role": "editor" }
}
```

Logout: POST `/auth/logout` clears the session and redirects to
`/`.

### Slack

The slash-command listener resolves the caller's email via
`users.info` and looks the role up in the same `RolesConfig`.
Hidden seats render as `"occupied (private)"` for viewers; full
details for editors / planning. See [Slack](./slack.md).

### CLI

The CLI is operator-only and unrestricted. No role flag. The
`SeatService` accepts `role=None` (CLI default) which means **no
filter** — full data passes through.

## How it works

### Auth-disabled mode

When the OIDC env vars are unset, the server runs without
`SessionMiddleware` and without `/auth/*` routes. This is the
default for local dev. An optional `X-Test-Role: viewer|editor|planning`
header drives role-aware behavior; **only honored when OIDC is
disabled**. Once `OIDC_ISSUER` etc. are set, the header is
silently ignored — production is session-only.

### Service-layer redaction

`SeatService.list_seats(role="viewer")` returns `Assignment` rows
with `employee_email=""`, `notes=""`, and a non-persisted
`redacted=True` flag set on `hidden=TRUE` rows. The web's
`_redact()` helper maps that to `"(private)"` in the JSON; Slack's
`_blocks` consults the same flag to choose the private-vs-occupied
template.

### Module layout

| File                           | Role                                                                                               |
| ------------------------------ | -------------------------------------------------------------------------------------------------- |
| `office_cli/_roles.py`         | `RolesConfig`, `resolve_roles`, `role_for_email`, `is_full_access`.                                |
| `office_cli/server/_auth.py`   | `OIDCConfig`, `resolve_oidc`, `register_auth_routes`, `current_user`, `role_from_user`.            |
| `office_cli/server/_routes.py` | `_spa_shell_response` issues the SSO redirect; `_build_floor_response` resolves role from session. |
| `office_cli/server/_app.py`    | Auto-resolves OIDC + roles when not passed explicitly.                                             |

### Session shape

`SessionMiddleware` (Starlette) signs a cookie containing
`{"user": {"email": "...", "role": "..."}}` after the OIDC
callback. The session cookie is `Secure`, `SameSite=Lax`, scoped
to the cookie domain by default.

`current_user(request)` reads the session in production; falls
back to the `X-Test-Role` header in auth-disabled mode.

### Open-redirect protection

`/auth/login?next=<path>` URL-encodes the `next` value end-to-end
so a URL like `/offices/tlv/floors/tlv-floor-5?seat=X&asOf=Y`
round-trips through the IdP intact. The handler whitelist-
validates `next`: must start with `/`, no `//` or `/\\` prefixes
(those would re-host the redirect).

## Limits + roadmap

- **No per-office role scoping.** One global role-map. Multi-office
  deployments where editor of office A shouldn't see office B
  data would need a richer config.
- **Planning role's draft-SVG view + future-dated visibility
  carve-outs** are deferred (issue #1 stretch). Lifting them is a
  one-line change in `is_full_access` plus a date-window pass in
  the service.
- **No API-token auth.** Non-browser callers go through the CLI.
  An `Authorization: Bearer` header with a service token could
  land Stage-9+ if needed.
- **Audit-log redaction is out of scope.** The audit log is
  operator-internal and append-only — full data is OK there.

## Related

- [Web map](./web-map.md) — the surface the redirect gates.
- [Slack `/whereis`](./slack.md) — caller-email → role pipeline.
- [BambooHR + auto-vacate](./bamboohr.md) — auto-vacate runs on
  the same data model that role gating filters; both apply at
  view time.
- [Architecture stages — Stage 7](../architecture.md) — PR-by-PR
  record.
