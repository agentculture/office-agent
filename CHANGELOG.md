# Changelog

All notable changes to this project will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/). This project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.8.0] - 2026-05-01

### Added

- v1 seating Stage 8 — DynamoDB store + bi-directional Sheets sync
  ([#12](https://github.com/agentculture/office-agent/issues/12)).
  New `office_cli.seats.dynamo` subpackage: `DynamoStore`,
  `DynamoAuditLog`, `DynamoClient` Protocol, `Boto3DynamoClient`
  production impl. Same Protocol shape and 5-minute TTL cache as
  the Sheets store, so the read path is identical across backends.
- `StorageConfig` extends to `type: "dynamo"` with
  `table_assignments`, `table_audit`, `region`. Configurable via
  `data/offices.yaml` `storage.dynamo:` block or env overrides
  (`OFFICE_DYNAMO_ASSIGNMENTS`, `OFFICE_DYNAMO_AUDIT`,
  `OFFICE_DYNAMO_REGION`). AWS credentials follow the standard
  chain (`AWS_PROFILE`, IAM role, etc) — never in YAML.
- New CLI verb `office seats migrate --from {csv,sheets,dynamo}
  --to {csv,sheets,dynamo} [--dry-run] [--audit-append] [--json]`
  for one-shot import/export between any two backends. Idempotent
  for assignments (upsert by `seat_id`); audit idempotency is
  target-dependent (Dynamo PK+SK dedups; CSV/Sheets append-only —
  command bails out if the target audit log is non-empty unless
  `--audit-append` is passed).
- New CLI verb `office seats sync --primary {sheets,dynamo}
  [--dry-run] [--json]` for bi-directional reconciliation between
  Sheets and Dynamo. Last-write-wins per row by `last_updated`.
  `--primary` is the tie-breaker when `last_updated` matches but
  content diverges. Idempotent: re-running converges. Operators
  run periodically (cron / GitHub Action) to keep the spreadsheet
  UI and the Dynamo runtime in agreement.
- `office_cli/seats/_sync.py`: pure `reconcile(left, right, *, primary,
  ...)` returning a `SyncPlan`. No I/O at the reconciliation layer
  so unit tests stay fast and surface-neutral.
- New optional extra: `pip install office-cli[dynamo]` pulls
  `boto3>=1.34`. Package still imports cleanly without it (lazy
  `boto3` import inside `Boto3DynamoClient.__init__`).
- `office_cli.seats.build_backends_for_type(data_dir, store_type)`
  exposed as a public helper for the migrate / sync verbs.

### Notes

- **Sheets stays a first-class runtime backend.** Stage 8 does not
  deprecate `OFFICE_STORE=sheets` — operators who prefer the
  spreadsheet UI as the primary editor can keep using it. The
  migrate + sync verbs make Sheets and Dynamo interoperable, not
  exclusive.
- **GSI on `employee_email`** is documented as Stage-9 hardening.
  The v1 read path is `scan` + in-memory filter (5-minute cache),
  matching Sheets behavior exactly.

## [0.7.0] - 2026-05-01

### Added

- v1 seating Stage 7 — SSO + roles
  ([#11](https://github.com/agentculture/office-agent/issues/11)).
  Three roles: `viewer` (default — sees `hidden=TRUE` seats as
  "occupied (private)"), `editor` (HR/IT — full details on hidden
  seats), `planning` (facilities — same as editor in v1; the
  draft-SVG and future-dated carve-outs from issue #1 are deferred).
- New `office_cli._roles` module: `RolesConfig`, `resolve_roles`,
  `role_for_email`, `is_full_access`. Roles map lives in
  `data/offices.yaml` under a top-level `roles:` block.
- `SeatService.list_seats(role=...)` and `whereis(email, role=...)`
  apply role-aware redaction at view time: viewer callers see hidden
  rows with cleared `employee_email` / `notes` and `redacted=True`.
  CLI passes no role and stays unrestricted.
- New optional extra: `pip install office-cli[sso]` pulls
  `authlib>=1.3`, `itsdangerous>=2.1`, and `httpx>=0.27`. The
  package still imports cleanly without it.
- Web SSO: new `office_cli.server._auth` module with `OIDCConfig`,
  `resolve_oidc`, `register_auth_routes`, `current_user`. When all
  five env vars (`OIDC_ISSUER`, `OIDC_CLIENT_ID`,
  `OIDC_CLIENT_SECRET`, `OIDC_REDIRECT_URL`, `SESSION_SECRET`) are
  set, `office serve` enables a SessionMiddleware-backed login flow;
  unauthenticated browsers are redirected to `/auth/login` and back
  to the originating URL after callback.
- Web auth-disabled mode for local dev / tests — when OIDC env vars
  are unset, the server runs without redirects. An optional
  `X-Test-Role` header drives role-aware behavior so tests can
  exercise viewer / editor / planning without sessions. The header
  is **only** honored when OIDC is disabled.
- `GET /api/floors/{id}` now returns a `user: {email, role}` field
  (or `null` when unauthenticated) so the SPA can render the signed-
  in identity in the header. Stage 7 adds a small `#user-info` slot
  with a logout button to the SPA shell.
- Slack `/whereis` resolves the calling user's email via the existing
  `users.info` flow and looks up their role. Hidden seats render as
  "occupied (private)" for viewer callers; editor/planning callers
  see the full block.

### Changed

- `Assignment` gains a non-persisted `redacted: bool = False` flag
  set by the service when role-aware redaction is applied. CSV /
  Sheets stores keep their existing column shape (`redacted` is a
  view-time signal only).

## [0.6.0] - 2026-05-01

### Added

- v1 seating Stage 6 — effective-date enforcement + `?asOf=`
  rendering ([#10](https://github.com/agentculture/office-agent/issues/10)).
  `SeatService.list_seats` and `SeatService.whereis` honor an optional
  `as_of` keyword; rows whose `[effective_from, effective_until]`
  window does not contain the requested date render as vacant.
- `office_cli._dates` — small helper module with `parse_iso_date`,
  `today_iso_date`, `is_effective`, and `validate_window`.
  `OfficeError(EXIT_USER_ERROR)` surfaces every malformed-date input
  with a clear remediation.
- New CLI flags: `office seats list --as-of YYYY-MM-DD`,
  `office whereis EMAIL --as-of YYYY-MM-DD`,
  `office seats assign SEAT EMAIL --from YYYY-MM-DD --until YYYY-MM-DD`.
- Web `GET /api/floors/{id}?as_of=YYYY-MM-DD` is honored end-to-end.
  Malformed dates surface as `400 {error, remediation}` via the
  existing `OfficeError` handler. The frontend banner copy moves from
  "as-of dates are not yet enforced (Stage 6)" to
  "Showing seat map as of YYYY-MM-DD."
- Slack `/whereis` accepts an optional trailing `YYYY-MM-DD` token —
  `/whereis alice@x 2026-07-01`, `/whereis @alice 2026-07-01`, and
  `/whereis 2026-07-01` (self lookup as-of the date) all work.

### Changed

- `SeatService.assign` (and `move`) write `effective_from` as a
  date-only `YYYY-MM-DD` value (date precision, no time component).
  `last_updated` and audit-log timestamps stay full ISO-8601 wall-
  clock strings. Pre-Stage-6 rows that wrote a full ISO timestamp
  into `effective_from` keep working — `is_effective` strips the
  `T...` suffix before comparison.

## [0.5.0] - 2026-05-01

### Added

- v1 seating Stage 5 — search-first web map
  ([#9](https://github.com/agentculture/office-agent/issues/9)). New
  `office_cli.server` subpackage with a FastAPI app exposing
  `/api/offices`, `/api/floors/{id}`, the SPA shell at
  `/offices/{id}/floors/{floor_id}` (HTML loaded from
  `office_cli/server/static/index.html`), the floor SVGs at
  `/svgs/{filename}.svg`, and a `/floors/{id}` short-URL
  redirect that resolves to the canonical SPA path so the Slack
  `/whereis` deep-link button (Stage 4) just works.
- New CLI verb `office serve [--host H] [--port N] [--data-dir D]`
  blocks on `uvicorn.run`. Reads from the same `build_service` factory
  as the CLI / Slack, so Stages 2 / 3 backends flow through.
- Vanilla-JS frontend (no build step) under
  `office_cli/server/static/`: `index.html` shell, `app.js` ES module
  (fetch + render + search + URL state), `app.css` (responsive
  layout), vendored Fuse.js for fuzzy search.
- New optional extra: `pip install office-cli[web]` pulls
  `fastapi>=0.110` and `uvicorn>=0.30`. The package still imports
  cleanly without it.
- Hidden-seat **server-side redaction**: `hidden=TRUE` rows render
  as `employee_email = "(private)"` and `notes = ""` in the JSON the
  browser sees, so the frontend cannot accidentally leak private
  details. Stage 7 will lift this for `editor` / `planning` roles.
- Auto-vacate (Stage 3) and the storage backends (Stage 2) flow
  through unchanged — the server reads through `SeatService` exactly
  like the CLI does.
- `?asOf=YYYY-MM-DD` URL parameter is parsed and surfaces a banner
  ("as-of dates are not yet enforced — Stage 6"). Service-layer
  filtering lands separately.

## [0.4.0] - 2026-05-01

### Added

- v1 seating Stage 4 — Slack `/whereis` slash command
  ([#8](https://github.com/agentculture/office-agent/issues/8)). New
  `office_cli.slack` subpackage wraps `SeatService.whereis` in a
  `slack_bolt` app and ships a `office slack-serve` CLI verb that
  blocks on `SocketModeHandler.start()`.
- New optional extra: `pip install office-cli[slack]` pulls
  `slack-bolt>=1.18` and `slack-sdk>=3.27`. The package still imports
  cleanly without it (lazy import inside `_serve.py`).
- Slash command supports three invocation shapes — `/whereis`
  (caller's own seat via `users.info`), `/whereis @user`
  (`<@U…>` mention parsed and resolved to email), and
  `/whereis email@domain` (plain text fallback).
- Block Kit response is **ephemeral by default** — only the caller
  sees the result. A deep-link button to the web map surfaces when
  `OFFICE_WEB_BASE_URL` is set (Stage 5 placeholder until the map
  ships).
- `hidden=TRUE` seats render as "occupied (private)" with no
  email/notes leakage; full-detail rendering is gated behind Stage 7
  roles.

## [0.3.0] - 2026-05-01

### Added

- v1 seating Stage 3 — BambooHR-backed `EmployeeDirectory` with the
  **auto-vacate killer feature** ([#7](https://github.com/agentculture/office-agent/issues/7)).
  When BambooHR no longer returns an employee in its `/v1/employees/directory`
  response, every seat assigned to them renders as vacant — the assignment
  row in the store is **not** mutated; the filter is applied at view time.
- New optional extra: `pip install office-cli[bamboohr]` pulls
  `requests>=2.31`. The CSV/stub paths still work without the dep tree.
- `office_cli.people.bamboohr` package: `BambooHRClient` Protocol,
  `RequestsBambooHRClient` (lazy import; thin shim over the BambooHR
  REST API), and `BambooHRDirectory` (5-minute TTL cache, fail-open on
  refresh errors with a stale-cache stderr warning).
- `office_cli._config.resolve_directory` picks the directory backend
  from `data/offices.yaml`'s `directory:` block, with env overrides
  `OFFICE_DIRECTORY` / `BAMBOOHR_API_TOKEN` / `BAMBOOHR_SUBDOMAIN`. The
  API token is **env-only** by design (never in YAML).
- `SeatService` now accepts an optional `directory` argument and
  applies the auto-vacate filter in `list_seats` and `whereis`. Default
  is `StubDirectory` so existing callers see no behavioral change.
- `build_service(data_dir)` resolves and threads through both the
  storage backend and the directory.

## [0.2.0] - 2026-05-01

### Added

- v1 seating Stage 2 — Google Sheets-backed `AssignmentStore` and append-only
  `AuditLog`. Selectable via `data/offices.yaml` (`storage.type: sheets`) or
  the `OFFICE_STORE` / `OFFICE_SHEETS_ID` / `OFFICE_SHEETS_SA` env vars.
- New optional extra: `pip install office-cli[sheets]` pulls `gspread>=6.0`.
  CSV users do not pay for the dep tree.
- `office_cli.seats.sheets` package: `SheetsStore`, `SheetsAuditLog`, and a
  thin `SheetsClient` shim so unit tests use a `FakeSheetsClient` without
  real credentials. Reads honor a 5-minute TTL cache; writes invalidate it.
- `build_service(data_dir)` picks the assignment-store / audit-log pair from
  the resolved storage config; the CSV path remains the default.

### Changed

- `office_cli.seats.__init__` re-exports the Sheets backends behind a
  guarded import so the package still loads cleanly without `gspread`.
- `office_cli.seats.AuditLog` is now a `Protocol` (mirroring the
  `AssignmentStore` shape from Stage 1). The CSV concrete class is
  `office_cli.seats.CsvAuditLog`. `AuditLog` is still re-exported, so
  type-checked downstream callers see the Protocol; runtime callers
  that constructed `AuditLog(path)` need to switch to `CsvAuditLog(path)`.

## [0.1.0] - 2026-05-01

### Added

- v1 seating Stage 1 (data + CLI core) per [issue #1](https://github.com/agentculture/office-agent/issues/1).
- Domain layer: `office_cli.offices`, `office_cli.floors`, `office_cli.seats`,
  `office_cli.people` packages with frozen dataclass models and a strict
  ID contract (`SEAT_RE`, `ROOM_RE`).
- `AssignmentStore` Protocol with a CSV-backed implementation (`CsvStore`)
  plus an append-only `AuditLog`. `SeatService` enforces "one seat per
  person globally" and writes audit entries on every mutation.
- Floor SVG parser and validator (`office_cli.floors.parse_svg`,
  `validate_floor`) covering the rules in the issue's SVG ID contract:
  ID format, uniqueness, viewBox, cluster-capacity match.
- New CLI verbs: `office floors list|validate`, `office seats list|assign|
  unassign|move|history`, `office whereis EMAIL`. All honor `--json`.
- Sample data: `data/offices.yaml` (one office, one floor),
  `floors/tlv-floor-5.svg` (placeholder traced floor, 6 seats + 1 room),
  `seats/{assignments,audit-log}.example.csv` schema examples.
- Runtime dependency: `PyYAML>=6.0`. SVG parsing uses the stdlib
  `xml.etree.ElementTree`; the historical bandit B314/B405 advisories no
  longer apply (Python's XML parsers were hardened upstream — see
  [python/cpython#135294](https://github.com/python/cpython/pull/135294)).
  These bandit checks are skipped via `pyproject.toml`.
- `docs/architecture.md` documenting Stage 1 scope and the deferred surfaces.

## [0.0.1] - 2026-05-01

### Added

- Initial scaffold: `office learn`, `office explain`, `office whoami` verbs
  on the agent-first CLI structure from `agentculture/afi-cli`
  (`cli/_errors.py`, `cli/_output.py`, `cli/_commands/`, `explain/`).
- `pyproject.toml` configured for PyPI distribution `office-cli`, Python
  package `office_cli`, CLI binary `office`, version `0.0.1`. Zero runtime
  dependencies.
- CI workflows: `tests.yml` (pytest with coverage, black/isort/flake8/bandit,
  markdownlint-cli2, version-check enforcing per-PR version bump);
  `publish.yml` (PyPI Trusted Publishing, TestPyPI dev-build smoke on PRs).
- Vendored skills from `agentculture/steward`: `version-bump`, `pr-review`,
  `run-tests`, `gh-issues`, `pypi-maintainer`, `notebooklm`, `sonarclaude`.
- Lint config: `.flake8`, `.markdownlint-cli2.yaml`.
- Per-machine skill config: `.claude/skills.local.yaml.example` (the active
  `.claude/skills.local.yaml` is git-ignored).
- `CLAUDE.md` updated to cover the post-bootstrap conventions while
  preserving the SVG ID contract and architectural guardrails for the v1
  seating system (issue #1).

[Unreleased]: https://github.com/agentculture/office-agent/compare/v0.8.0...HEAD
[0.8.0]: https://github.com/agentculture/office-agent/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/agentculture/office-agent/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/agentculture/office-agent/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/agentculture/office-agent/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/agentculture/office-agent/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/agentculture/office-agent/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/agentculture/office-agent/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/agentculture/office-agent/compare/v0.0.1...v0.1.0
[0.0.1]: https://github.com/agentculture/office-agent/releases/tag/v0.0.1
