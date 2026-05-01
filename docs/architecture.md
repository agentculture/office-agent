# Architecture — v0.8.0 (Stages 1–8)

`office` ships in stages on top of issue
[#1](https://github.com/agentculture/office-agent/issues/1). This document
captures **what is implemented today** and **what is deferred** so the
boundary stays explicit.

## Layered model

```text
   CLI verbs (office_cli.cli._commands)
            │
            ▼
   SeatService  ──►  AssignmentStore (Protocol)
   (office_cli.seats._service)        │
            │                         ├── CsvStore       ✓ implemented
            ▼                         ├── SheetsStore    ◌ deferred
   AuditLog (append-only CSV)         └── DynamoStore    ◌ deferred
            │
            ▼
   Office topology (office_cli.offices)
   ── load_offices(data_dir) → {Office → Floor → Cluster, Room}

   Floor SVG layer (office_cli.floors)
   ── parse_svg(path) → FloorSvg
   ── validate_floor(svg, floor) → list[Issue]
```

`office_cli.people` exposes an `EmployeeDirectory` Protocol with two
implementations: `StubDirectory` (default — trusts whatever email it
receives) and `BambooHRDirectory` (5-min TTL cache; presence in
BambooHR's `/v1/employees/directory` is the auto-vacate signal). The
service applies a view-time auto-vacate filter: a seat whose stored
email is no longer active in the directory renders as vacant.

## Stage 1 — implemented in v0.1.0

- Frozen-dataclass domain models: `Office`, `Floor`, `Cluster`, `Room`,
  `Assignment`, `AuditEntry`, `Employee`.
- `data/offices.yaml` schema (`load_offices`).
- Floor SVG parser (`parse_svg`) — reads `<rect>` / `<polygon>` with `id`
  and `class`; ignores everything else.
- Validator (`validate_floor`) — view-box, ID format, cluster mapping,
  duplicate IDs, untagged-but-shaped IDs, capacity mismatch (warning).
- CSV-backed `AssignmentStore` (`CsvStore`) and append-only `AuditLog`.
- `SeatService` invariants: seat must exist; one seat per email
  globally; every mutation writes audit.
- CLI verbs: `office floors list|validate`, `office seats list|assign|
  unassign|move|history`, `office whereis EMAIL`. Every verb honors
  `--json` and the shared `--data-dir`.
- Sample data: `data/offices.yaml` (one office, one floor),
  `floors/tlv-floor-5.svg` (placeholder), `seats/*.example.csv`.
- Test fixtures + parametric tests on the ID contract, SVG parser,
  validator, store, service, and each CLI verb (text and JSON).

## Stage 2 — implemented in v0.2.0

- `office_cli.seats.sheets.SheetsStore` and `SheetsAuditLog` implement the
  same `AssignmentStore` / append-only audit contracts as the CSV pair.
- A thin `SheetsClient` Protocol (`read_rows`, `replace_rows`,
  `append_rows`) lives between the store and `gspread`, so unit tests
  use a `FakeSheetsClient` and never need real credentials.
- `GspreadClient` is the production adapter; gspread is imported lazily,
  so installations without the `[sheets]` extra still load
  `office_cli.seats` cleanly.
- 5-minute read cache (per-store, per-process); writes invalidate it.
- Storage selection (`office_cli._config.resolve_storage`):

  1. `storage:` block in `data/offices.yaml`,
  2. `OFFICE_STORE` / `OFFICE_SHEETS_ID` / `OFFICE_SHEETS_SA` env vars,
  3. CSV by default.

Install the extra to use Sheets:

```bash
pip install office-cli[sheets]
```

Configure either via `data/offices.yaml`:

```yaml
storage:
  type: sheets
  sheets:
    spreadsheet_id: "1abc..."
    service_account: "data/sheets-service-account.json"
    cache_ttl_seconds: 300
```

…or via env vars (which override the YAML block):

```bash
export OFFICE_STORE=sheets
export OFFICE_SHEETS_ID=1abc...
export OFFICE_SHEETS_SA=/abs/or/data-dir-relative/sa.json
```

The service-account JSON should be **git-ignored**.

## Stage 3 — implemented in v0.3.0

- `office_cli.people.bamboohr.BambooHRDirectory` implements
  `EmployeeDirectory` against the BambooHR `/v1/employees/directory`
  endpoint with a 5-minute TTL cache.
- `RequestsBambooHRClient` is the production adapter; `requests` is
  imported lazily so installs without the `[bamboohr]` extra still
  load `office_cli.people` cleanly.
- `BambooHRClient` Protocol exposes only `fetch_directory()`; tests use
  a `FakeBambooHRClient` and never need real credentials.
- **Fail-open**: a refresh failure with a populated cache logs to stderr
  and serves the previous snapshot. Only a first-fetch failure raises
  `OfficeError(EXIT_ENV_ERROR)`.
- **Auto-vacate** is implemented in `SeatService` via
  `_apply_autovacate`: rows whose stored email is missing from the
  directory render as vacant in `list_seats` / `whereis`. The store
  row is **not mutated** — history and the underlying CSV/Sheet stay
  intact, so reactivating an employee restores the seat without any
  write.
- **API token is env-only**: `BAMBOOHR_API_TOKEN` must never be
  committed to `data/offices.yaml`. The YAML block carries
  `subdomain` and `cache_ttl_seconds` only.

Install the extra to use BambooHR:

```bash
pip install office-cli[bamboohr]
```

Configure either via `data/offices.yaml`:

```yaml
directory:
  type: bamboohr
  bamboohr:
    subdomain: tipalti
    cache_ttl_seconds: 300
```

…plus the API token in the env (never in YAML):

```bash
export BAMBOOHR_API_TOKEN=...
```

…or full env override:

```bash
export OFFICE_DIRECTORY=bamboohr
export BAMBOOHR_SUBDOMAIN=tipalti
export BAMBOOHR_API_TOKEN=...
```

## Stage 4 — implemented in v0.4.0

- `office_cli.slack` subpackage wraps `SeatService.whereis` in a
  `slack_bolt` app. The handler is structurally typed (any `client`
  with `users_info` + `chat_postEphemeral`) so unit tests use a
  `FakeSlackApp` + `FakeSlackClient` and never touch the SDK or the
  network.
- New CLI verb `office slack-serve` blocks on
  `SocketModeHandler.start()`. **Socket Mode only** for v1 — no HTTP
  endpoint, no signing-secret middleware. Requires both
  `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN`.
- Three invocation shapes for `/whereis`:
  - empty → look up the caller's seat (resolves their email via
    `users.info`),
  - `<@U…>` mention → resolve mentioned user's email,
  - plain text containing an email → use it directly.
- Responses are **ephemeral** by default — looking up a coworker's
  seat does not broadcast to the channel. `hidden=TRUE` seats render
  as "occupied (private)" with no email/notes leakage; Stage 7 will
  lift the filter for `editor`/`planning` roles.
- Setting `OFFICE_WEB_BASE_URL` adds an "Open map" deep-link button
  (placeholder until Stage 5 ships the web map).
- BambooHR auto-vacate (Stage 3) flows through transparently: a
  `/whereis` for an offboarded employee returns "no seat assigned".

Install the extra to use Slack:

```bash
pip install office-cli[slack]
```

Run:

```bash
SLACK_BOT_TOKEN=xoxb-... SLACK_APP_TOKEN=xapp-... office slack-serve
```

Required Slack app scopes: `commands`, `users:read.email`, `chat:write`.

## Stage 5 — implemented in v0.5.0

- `office_cli.server` subpackage builds a FastAPI app on top of
  `SeatService.list_seats`. Routes:
  - `GET /api/offices` — office/floor topology JSON.
  - `GET /api/floors/{floor_id}` — merged floor + assignments JSON
    with **server-side redaction** for `hidden=TRUE` rows
    (`employee_email = "(private)"`, `notes = ""`).
  - `GET /floors/*.svg` — the traced floor SVGs as static files.
  - `GET /static/*` — the bundled vanilla-JS frontend.
  - `GET /offices/{id}/floors/{floor_id}` — the SPA shell HTML.
- `office serve [--host H] [--port N] [--data-dir D]` blocks on
  `uvicorn.run`. Uses the same `build_service` factory as the CLI /
  Slack — Stages 2 / 3 backends flow through.
- **Frontend**: vanilla JS, no build step. Single ES module reads
  the URL, fetches the merged view, inlines the SVG, walks the IDed
  shapes to set `occupied` / `private` / `highlighted` CSS classes,
  and runs an in-process Fuse-style fuzzy search across seat IDs and
  assigned emails.
- URL is canonical state — `/offices/{id}/floors/{floor_id}?seat={sid}&asOf={date}`.
  `history.pushState` keeps deep links round-tripping. `?asOf=` is
  parsed and surfaces a banner; service-layer enforcement is Stage 6.
- Mobile-responsive (sidebar collapses below 800px).
- Auto-vacate (Stage 3) flows through unchanged: an offboarded
  employee's seat renders as vacant in the map.

Install the extra to use the web map:

```bash
pip install office-cli[web]
```

Run:

```bash
office serve --port 8000
```

The vendored fuzzy-search shim under `office_cli/server/static/vendor/`
is intentionally minimal — see the README there for when to swap in
the upstream Fuse.js library.

## Stage 6 — implemented in v0.6.0

Effective-date enforcement ([#10](https://github.com/agentculture/office-agent/issues/10)).
The `effective_from` / `effective_until` columns reserved by Stage 1 +
2 are now read at view time:

- `SeatService.list_seats(as_of=...)` and `SeatService.whereis(email,
  as_of=...)` filter rows whose window does not contain the requested
  date. Auto-vacate (Stage 3) runs after the date filter, so a seat
  assigned to a future-dated employee renders vacant today regardless
  of directory state.
- `SeatService.assign(effective_from=..., effective_until=...)`
  defaults `effective_from` to today (date-only `YYYY-MM-DD`) and
  leaves `effective_until` open-ended. `validate_window` rejects an
  inverted `until < from`.
- All four surfaces honor it: `office seats list --as-of`,
  `office whereis --as-of`, `office seats assign --from / --until`,
  the web `?as_of=YYYY-MM-DD` query param, and a trailing
  `YYYY-MM-DD` token on Slack `/whereis`.
- Storage shape: `effective_from` / `effective_until` are written as
  date-only `YYYY-MM-DD`. `last_updated` and audit-log timestamps stay
  full ISO-8601 wall-clock strings. Pre-Stage-6 rows that wrote a full
  ISO timestamp into `effective_from` keep working — `is_effective`
  strips the `T...` suffix before lex comparison.
- All malformed-date inputs surface as `OfficeError(EXIT_USER_ERROR)`
  with a remediation, and the web routes map that to
  `400 {error, remediation}` via the existing handler.

## Stage 7 — implemented in v0.7.0

SSO + roles ([#11](https://github.com/agentculture/office-agent/issues/11)).
Three roles: `viewer` (default — sees `hidden=TRUE` seats as
"occupied (private)"), `editor` (HR/IT — full details on hidden
seats), `planning` (facilities — same as editor in v1).

- `office_cli/_roles.py`: `RolesConfig`, `resolve_roles`,
  `role_for_email`, `is_full_access`. Roles map lives in
  `data/offices.yaml` under a top-level `roles:` block —
  `editor: [...]` / `planning: [...]` lists of emails. Anything not
  listed is `viewer`.
- `SeatService.list_seats(role=...)` and `whereis(role=...)` apply
  role-aware redaction at view time. `role=None` (CLI default) is
  unrestricted; `role="viewer"` clears `employee_email` / `notes`
  on `hidden=TRUE` rows and sets `redacted=True` (a non-persisted
  view-time flag on `Assignment`). Surface renderers consult
  `redacted` to render the `"(private)"` placeholder.
- Web SSO via `office_cli/server/_auth.py` — `OIDCConfig`,
  `register_auth_routes` (using `authlib.integrations.starlette_client`).
  When all five env vars (`OIDC_ISSUER`, `OIDC_CLIENT_ID`,
  `OIDC_CLIENT_SECRET`, `OIDC_REDIRECT_URL`, `SESSION_SECRET`) are
  set, the SPA shell route requires auth and unauth browsers are
  redirected through the IdP.
- Auth-disabled mode: when OIDC env vars are unset, the server runs
  without redirects (local dev). Tests use the `X-Test-Role`
  header to drive role-aware behavior; the header is **only**
  honored when OIDC is disabled (production sets the env vars and
  ignores it).
- Slack `/whereis` resolves the calling user's email via the
  existing `users.info` flow and looks up their role from
  `RolesConfig`. The block-level "occupied (private)" path is now
  gated on `assignment.redacted`, not on `assignment.hidden`, so
  editor / planning callers see the full block.
- Audit-log redaction is explicitly out of scope (issue #11) — the
  audit log is operator-internal and append-only; full data is OK.
- The planning role's draft-SVG and future-dated visibility carve-outs
  from issue #1 stay deferred.

## Stage 8 — implemented in v0.8.0

DynamoDB store + bi-directional Sheets sync
([#12](https://github.com/agentculture/office-agent/issues/12)).

- `office_cli/seats/dynamo/`: `DynamoStore` + `DynamoAuditLog` behind
  the same `AssignmentStore` / `AuditLog` Protocols as the Sheets
  backend. The `DynamoClient` Protocol exposes only the four
  operations the store + audit need (`scan_all`, `put_item`,
  `batch_put`, `query_by_pk`); `Boto3DynamoClient` is the production
  implementation with lazy `boto3` import. Tests use a hand-rolled
  `FakeDynamoClient` (no `moto` dependency).
- Schema: `office-assignments` table keyed on `seat_id`;
  `office-audit-log` keyed on (`seat_id`, `timestamp`). The audit
  PK+SK pair makes `put_item` idempotent — re-runs of `migrate`
  overwrite the same rows rather than duplicating them.
- Read path: `DynamoStore.list()` does one `scan` and caches with a
  5-minute TTL, identical to `SheetsStore`. `by_email` filters in
  memory. A GSI on `employee_email` is documented as Stage-9
  hardening but not required for v1 scale.
- `office seats migrate --from {csv,sheets,dynamo} --to {csv,sheets,dynamo}
  [--dry-run] [--audit-append]`: one-shot import/export between any
  two backends. Idempotent for assignments (upsert by `seat_id`);
  audit idempotency is target-dependent.
- `office seats sync --primary {sheets,dynamo} [--dry-run]`:
  bi-directional reconciliation between Sheets and Dynamo with
  last-write-wins per row by `last_updated`. `office_cli/seats/_sync.py`
  hosts the pure `reconcile()` reconciler — no I/O at the
  reconciliation layer.
- **Sheets stays a first-class runtime backend**. Stage 8 adds
  Dynamo as an alternative; it does not deprecate Sheets. Operators
  who prefer the spreadsheet UI as their primary editor keep using
  it. The migrate + sync verbs make them interoperable.

## Deferred surfaces

Each is a separate issue/PR.

| Stage              | Surface                                       | Notes                                                                   |
| ------------------ | --------------------------------------------- | ----------------------------------------------------------------------- |
| 9. GSI + observability | `employee_email` GSI on `office-assignments` | Drops the `scan` + in-memory filter for `by_email`.                     |

## Operating notes

- Real assignment data lives in `seats/assignments.csv` and
  `seats/audit-log.csv`; both are git-ignored. Only the `*.example.csv`
  files are checked in as schema documentation.
- `OFFICE_DATA_DIR` (or `--data-dir DIR`) overrides where the CLI looks
  for `data/`, `floors/`, and `seats/`.
- The audit log is append-only by contract. "Who used to sit at X?" is
  literally the chronological projection of the audit-log CSV.
- `office_cli.seats.SeatService._build_seat_index` unions every loaded
  floor's seat IDs *and* every room declared in YAML, so rooms remain
  assignable even before someone traces them.
