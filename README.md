# office

Agent-first CLI for managing seat assignments and meeting rooms across
office floor plans. Floor layouts are hand-traced SVGs; people come from
BambooHR; assignments live in a Google Sheet (v1) or DynamoDB (v2). The
CLI exposes the same operations as the Slack `/whereis` command and the
web map.

> **Status — v0.8.0.** Stages 1–8 of the v1 seating system are in:
> floor SVG parser/validator, CSV / Google Sheets / DynamoDB-backed
> assignment store with append-only audit log, BambooHR-backed
> `EmployeeDirectory` with the auto-vacate killer feature, CLI verbs
> (`floors`, `seats`, `whereis`), a Slack `/whereis` slash-command
> listener, a search-first web map, effective-date enforcement,
> SSO + role-aware redaction, and bi-directional Sheets ↔ Dynamo
> sync. See
> [issue #1](https://github.com/agentculture/office-agent/issues/1).

## Naming surfaces

`office` uses three different identifiers across packaging surfaces. Mind
the split — do not blanket-replace one token across the codebase.

| Surface             | Value         |
| ------------------- | ------------- |
| GitHub repo         | `agentculture/office-agent` |
| PyPI distribution   | `office-cli`  |
| Python package      | `office_cli`  |
| CLI binary          | `office`      |
| Error class prefix  | `Office`      |

## Install

```bash
uv tool install office-cli
office --version
```

## Use

```bash
office learn                                    # self-teaching prompt
office explain seats                            # markdown docs for any verb
office whoami --json                            # auth probe (stub)

# v0.1.0 seating verbs:
office floors list --json
office floors validate floors/tlv-floor-5.svg
office seats list --vacant
office seats assign 5-T-01 alice@example.com
office seats move alice@example.com 5-T-02
office seats history 5-T-01 --json
office whereis alice@example.com
```

`office` reads `data/offices.yaml`, `floors/`, and `seats/` from the
current working directory. Override with `--data-dir DIR` or
`OFFICE_DATA_DIR=DIR`.

### Storage backend

`office` defaults to CSV-backed storage under `seats/` (`assignments.csv`,
`audit-log.csv`). To use Google Sheets instead:

```bash
pip install office-cli[sheets]
export OFFICE_STORE=sheets
export OFFICE_SHEETS_ID=1abc...
export OFFICE_SHEETS_SA=/path/to/service-account.json
```

…or declare it in `data/offices.yaml`:

```yaml
storage:
  type: sheets
  sheets:
    spreadsheet_id: "1abc..."
    service_account: "data/sheets-service-account.json"
    cache_ttl_seconds: 300
```

Reads honor a 5-minute TTL cache; writes invalidate it. See
`docs/architecture.md` for the full storage contract.

### People directory (BambooHR)

`office` defaults to a no-op `StubDirectory` that trusts whatever email
it receives. Switch to BambooHR for the auto-vacate killer feature
(seats render as vacant automatically when an employee is offboarded).

> **Note:** the BambooHR backend is gated off by default. Set
> `OFFICE_BAMBOOHR_ENABLED=1` in addition to the config below; without
> it, even valid BambooHR settings silently fall back to the stub
> directory (with a one-line warning to stderr).

```bash
pip install office-cli[bamboohr]
export OFFICE_BAMBOOHR_ENABLED=1   # required: opt in to the gated feature
export OFFICE_DIRECTORY=bamboohr
export BAMBOOHR_SUBDOMAIN=tipalti
export BAMBOOHR_API_TOKEN=...   # env-only — do not commit
```

…or declare the public bits in `data/offices.yaml` and keep the token
in the env:

```yaml
directory:
  type: bamboohr
  bamboohr:
    subdomain: tipalti
    cache_ttl_seconds: 300
```

The directory affects rendering only; assignments stay in the store
unchanged. Re-activating an employee in BambooHR restores their seat
without any write.

### Slack `/whereis`

Run a Slack `/whereis` slash command backed by the same `SeatService`:

```bash
pip install office-cli[slack]
export SLACK_BOT_TOKEN=xoxb-...
export SLACK_APP_TOKEN=xapp-...
office slack-serve
```

Required Slack app scopes:

- `commands` — to register `/whereis`.
- `users:read.email` — for `users.info` to return `profile.email`.
- `chat:write` — to post the ephemeral response.

Three invocation shapes:

- `/whereis` — looks up the caller's own seat.
- `/whereis @user` — Slack mention; resolves the user's email.
- `/whereis email@domain` — plain text fallback.

A trailing `YYYY-MM-DD` token on any of the three shapes filters by
effective date — e.g. `/whereis alice@x 2026-07-01` returns Alice's
seat as of that date.

Responses are **ephemeral by default** — only the caller sees them.
`hidden=TRUE` seats render as "occupied (private)" until role gating
(Stage 7) lifts the filter for privileged callers. Setting
`OFFICE_WEB_BASE_URL` to your `office serve` deployment adds an
"Open map" deep-link button to the response.

### Effective-date windows

Assignments can carry an effective window so the seat map renders "as
of" any date:

```bash
office seats assign 5-T-01 alice@example.com --from 2026-07-01 --until 2026-12-31
office whereis alice@example.com                     # default = today
office whereis alice@example.com --as-of 2026-07-15  # inside the window
office seats list --as-of 2026-09-01
```

The web map honors `?asOf=YYYY-MM-DD` in the URL —
`http://localhost:8000/offices/tlv/floors/tlv-floor-5?asOf=2026-07-15`
shows the same view, deep-linkable.

`effective_from` / `effective_until` are stored as `YYYY-MM-DD` (date
precision); `last_updated` and audit-log timestamps stay full ISO-8601.
Empty bounds mean "always begins" / "no end".

### DynamoDB backend + Sheets sync

`office` ships three storage backends behind a single Protocol: CSV
(default), Google Sheets, and DynamoDB. They are interchangeable
runtime backends; pick one via `OFFICE_STORE` or
`storage.type` in `data/offices.yaml`.

```bash
pip install office-cli[dynamo]
export OFFICE_STORE=dynamo
export OFFICE_DYNAMO_ASSIGNMENTS=office-assignments
export OFFICE_DYNAMO_AUDIT=office-audit-log
export OFFICE_DYNAMO_REGION=us-east-1
# AWS creds via AWS_PROFILE / IAM role / standard chain
office seats list
```

YAML:

```yaml
storage:
  type: dynamo
  dynamo:
    table_assignments: office-assignments
    table_audit: office-audit-log
    region: us-east-1
    cache_ttl_seconds: 300
```

The `office-assignments` table is keyed on `seat_id`. The
`office-audit-log` table is keyed on `seat_id` (PK) + `timestamp`
(SK) so re-running migrations doesn't duplicate audit rows.

#### One-shot import/export

```bash
# Bootstrap Dynamo from Sheets:
office seats migrate --from sheets --to dynamo --dry-run   # preview
office seats migrate --from sheets --to dynamo

# Snapshot Dynamo back to Sheets for offline review:
office seats migrate --from dynamo --to sheets --audit-append
```

#### Bi-directional sync (Sheets ↔ Dynamo)

Sheets stays the human-friendly editor; Dynamo is the runtime read
path. Run `office seats sync` periodically (cron / GitHub Action) to
reconcile both sides via last-write-wins on `last_updated`:

```bash
# Pick the tie-breaker side when last_updated matches but content
# diverges (rare). The reconcile is idempotent — re-running converges.
office seats sync --primary sheets --dry-run
office seats sync --primary sheets
```

The CLI is the supported sync entry point; there is no always-on
daemon (a Stage-9+ addition if needed).

### SSO + roles

The web frontend can be gated behind your IdP via OIDC. Three roles
are recognized: `viewer` (default — sees `hidden=TRUE` seats as
"occupied (private)"), `editor` (HR/IT — full details on hidden
seats), and `planning` (facilities — same as editor in v1).

```bash
pip install office-cli[sso,web]
export OIDC_ISSUER=https://your-idp.example.com
export OIDC_CLIENT_ID=office-agent
export OIDC_CLIENT_SECRET=xxx
export OIDC_REDIRECT_URL=https://office.example.com/auth/callback
export SESSION_SECRET=$(openssl rand -hex 32)
office serve --port 8000
```

Role mapping lives in `data/offices.yaml` under a top-level `roles:`
block:

```yaml
roles:
  editor:
    - "hr-it@tipalti.com"
    - "alice@tipalti.com"
  planning:
    - "facilities@tipalti.com"
```

Anything not listed is `viewer` — including unmatched authenticated
users.

When the OIDC env vars are unset, `office serve` runs in
**auth-disabled** mode: no redirects, no session middleware, every
request is anonymous. This is the default for local dev. An optional
`X-Test-Role: editor` request header drives role-aware behavior in
that mode (useful for `curl` smoke tests). The header is **only**
honored when OIDC is disabled.

The CLI is operator-only and **always** unrestricted (no role flag).
Slack `/whereis` resolves the calling user's role from their email
via the same roles map.

## Adding a new floor

1. **Trace the floor in Inkscape** following `docs/tracing-guide.md` and
   the SVG ID contract in `CLAUDE.md`. Save as Plain SVG.
2. **Drop the SVG into `floors/`** as `<office>-floor-<N>.svg`.
3. **Add an entry to `data/offices.yaml`** with cluster capacities and
   any named rooms.
4. Verify: `office floors validate floors/<file>.svg`. Errors fail the
   command; warnings (e.g. cluster-capacity mismatches) are
   informational.

## Develop

```bash
uv sync
uv run pytest -n auto -v
uv run office --version
uv run python -m office_cli
```

## License

MIT — see `LICENSE`.
