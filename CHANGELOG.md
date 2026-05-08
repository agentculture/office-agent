# Changelog

All notable changes to this project will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/). This project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.10.2] - 2026-05-08

### Added

- `.claude/skills/process-pdf` skill: `pdf-to-png.sh` extracts a single page from a multi-page PDF as a 1920-wide PNG suitable for the floor-map tracing background. Pages can be selected by 1-based number or by text label (`pdftotext` search). Requires `poppler` (`pdftoppm` + `pdftotext`); the skill never installs anything itself. Documented in SKILL.md and cross-linked from `docs/tracing-guide.md`. Replaces the manual `sips`+page-extraction dance that was inline in the trace flow.
- `.env.example` documents the `OFFICE_DRIVE_*` env vars introduced in #44 so operators have one place to copy from.

## [0.10.1] - 2026-05-07

### Added

- `docs/tracing-guide.md` walkthrough for producing floor SVGs in Inkscape: document setup, the id/class contract, scaling Inkscape workflow, save-as-Plain-SVG, validation loop, common gotchas, end-to-end checklist. Cross-linked from `docs/floors-from-drive.md`. ([#15](https://github.com/agentculture/office-agent/issues/15))

## [0.10.0] - 2026-05-07

### Added

- Drive-as-CMS backend: when `OFFICE_DRIVE_ROOT` is set, hydrate `offices.yaml` and floor SVGs from a Google Drive folder into a local cache instead of reading from the working directory. Drive layout is one folder per office (folder name ends with `(<office-id>)`); the hydrator translates Drive's bare-filename SVGs into the existing `floors/<filename>` shape so downstream code is unchanged. Optional `[drive]` extra brings `google-api-python-client`. Knobs: `OFFICE_DRIVE_CREDENTIALS` (defaults to the Sheets SA), `OFFICE_DRIVE_TTL_SECONDS` (default 300), `OFFICE_DRIVE_CACHE_DIR` (default `~/.cache/office-cli/drive`). See `docs/floors-from-drive.md`. ([#44](https://github.com/agentculture/office-agent/issues/44))
- `data/offices.yaml.example` documents the local-fallback shape for operators migrating to Drive mode.

## [0.9.9] - 2026-05-05

### Added

- Slack `/whereis` now resolves partial / misspelled names via a
  third resolution tier on top of the exact local-part path
  ([#29](https://github.com/agentculture/office-agent/issues/29)) and
  exact roster-name path
  ([#38](https://github.com/agentculture/office-agent/issues/38)).
  When neither exact tier hits, a stdlib-`difflib` scorer ranks the
  union of assignment-store local-parts and Slack roster names
  (when the directory is enabled) against the bare token. A single
  candidate above the cutoff — or one that exceeds the runner-up by
  the auto-pick gap — resolves directly to the seat. Otherwise the
  handler renders an interactive disambiguation message: one section
  per candidate with a *This person* button. Clicking the button
  fires a new `whereis_pick` action that re-runs the lookup against
  the picked email and replaces the original ephemeral with the seat
  result via `response_url`. Hidden / redacted seats keep their
  privacy treatment through both the auto-pick and button-driven
  paths. ([#39](https://github.com/agentculture/office-agent/issues/39))

- `OFFICE_FUZZY_CUTOFF` (float in `[0.0, 1.0]`, default `0.7`) and
  `OFFICE_FUZZY_LIMIT` (positive int, default `5`) tune the new
  tier on the slack-serve entry point. Misconfigured values raise
  `EXIT_ENV_ERROR` before slack-bolt construction so a bad deploy
  doesn't get masked by a downstream `BoltError`.
  ([#39](https://github.com/agentculture/office-agent/issues/39))

## [0.9.8] - 2026-05-05

### Added

- Slack `/whereis` now resolves bare names against the Slack workspace
  roster as a follow-up to the email-local-part path landed in
  [#29](https://github.com/agentculture/office-agent/issues/29).
  When `find_by_local_part` returns no hits, the handler falls
  through to a TTL-cached (`OFFICE_SLACK_DIRECTORY_TTL`-tunable;
  default 300s) `users.list` lookup against `display_name`,
  `real_name`, and `name`. Exact match wins; multiple matches render
  the new `disambiguation_users` block (display name + email per
  candidate) so the caller can re-run with the unambiguous email.
  Bots, deleted users, and members without a profile email are
  excluded from the cache. The lookup is fail-open: a transient
  `users.list` outage keeps serving the previous cache and emits a
  stderr diagnostic, and a first-attempt failure logs and falls
  through to the no-match block instead of crashing the listener.
  ([#38](https://github.com/agentculture/office-agent/issues/38))

- `OFFICE_SLACK_DIRECTORY` env var (read by `office slack-serve`)
  short-circuits the new path entirely. Set to `disabled` / `off` /
  `0` / `false` / `no` (case-insensitive) to skip every `users.list`
  call — recommended for workspaces with tens of thousands of
  members where the roster fetch is wasteful and the local-part path
  plus explicit emails are sufficient.
  ([#38](https://github.com/agentculture/office-agent/issues/38))

## [0.9.7] - 2026-05-05

### Added

- Slack `/whereis` (or any `OFFICE_SLACK_COMMAND` override) now accepts
  a bare name or username (`/whereis ori.nachum`) and resolves it
  against the assignment store's email local-parts (case-insensitive).
  The failed-autocomplete shape (`@ori.nachum` — what Slack sometimes
  substitutes when the proper `<@Uxxx>` markup doesn't fire) is treated
  identically. When a bare token matches a single assignment the seat
  renders as before; when it matches two or more (same local-part
  across multiple email domains) the handler renders an ephemeral
  disambiguation list with the full emails so the caller can re-run
  with the unambiguous form. Hidden seats keep the redaction
  treatment in the disambiguation list. The unparseable-text block now
  mentions name + `@mention` + email as accepted input forms.
  ([#29](https://github.com/agentculture/office-agent/issues/29))

  This is the MVP slice of the resolution chain in #29. Two follow-ups
  cover the rest of the chain:
  [#38](https://github.com/agentculture/office-agent/issues/38) adds
  Slack `users.list` exact-name lookup with a TTL cache and an
  opt-out env var;
  [#39](https://github.com/agentculture/office-agent/issues/39) adds
  fuzzy / partial matching with an interactive disambiguation UI.

## [0.9.6] - 2026-05-05

### Changed

- **Breaking:** `office seats move` now takes positional arguments in
  the order `<seat_id> <email>`, matching `office seats assign`. The
  previous order was `<email> <new_seat_id>`, which gave operators no
  consistent mental model when alternating between the two verbs.
  Update any scripts or muscle memory that called
  `office seats move alice@example.com 5-T-02` to
  `office seats move 5-T-02 alice@example.com`.
  ([#30](https://github.com/agentculture/office-agent/issues/30))

### Fixed

- `office seats move` now detects the wrong-order case (`@` in the
  first arg, none in the second) and emits a remediation hint
  pointing at the correct invocation, instead of the previous
  misleading `error: unknown seat: alice@example.com`.
  ([#30](https://github.com/agentculture/office-agent/issues/30))

## [0.9.5] - 2026-05-05

### Fixed

- `SheetsAuditLog.append_many` now seeds the `audit-log` schema header
  even when the tab was just auto-created by gspread. Auto-created tabs
  (`add_worksheet(rows=1, cols=10)`) read back as a single phantom row
  of empty strings, which the previous existence check treated as
  "already populated" — the header was skipped, `audit.all()` parsed
  row 1 as schema, and `office seats history <seat>` then returned no
  rows even though `migrate` had written them. The check now ignores
  rows that are entirely whitespace, so the first `append_many` against
  a freshly created tab seeds the header and the data rows together.
  ([#32](https://github.com/agentculture/office-agent/issues/32))

## [0.9.4] - 2026-05-05

### Fixed

- Slack `/whereis` (or any `OFFICE_SLACK_COMMAND` override) invoked with
  no arguments now renders *"you sit at &lt;seat&gt;"* — second-person
  agreement — instead of the previous *"you sits at &lt;seat&gt;"*. The
  third-person paths (`alice@example.com sits…`, `<@U123> sits…`)
  are unchanged. `office_cli.slack._blocks.occupied()` gained a
  `verb: str = "sits"` kwarg; the handler picks `"sit"` when
  `target.self_lookup` is true.
  ([#27](https://github.com/agentculture/office-agent/issues/27))

## [0.9.3] - 2026-05-05

### Fixed

- `office seats migrate` now writes one row per assignable seat-or-room
  declared by the office topology — vacant rows for never-assigned
  ids — so the target backend mirrors the full universe (union of SVG
  `seat_ids`, SVG `room_ids`, and YAML-declared rooms; matches
  `SeatService._build_seat_index`). The previous behavior wrote only
  "touched" rows, leaving the Google Sheet sparse and undercutting the
  Sheets-as-CMS architectural promise in `CLAUDE.md`. Two flavors of
  orphan are surfaced separately: **source orphans** (rows in source
  not in any SVG/YAML — kept, never deleted) and **target orphans**
  (rows in target neither in source nor in the universe — kept, never
  deleted, but now flagged so dry-run no longer reports a falsely
  "all unchanged" status while the target diverges from the universe).
  Both surface on stderr and in the JSON summary as
  `assignments_orphans` / `assignments_target_orphans`.
  ([#33](https://github.com/agentculture/office-agent/issues/33))

## [0.9.2] - 2026-05-05

### Added

- `OFFICE_SLACK_COMMAND` env var (and matching `command_name` kwarg on
  `office_cli.slack.build_app`) to rebind the listener away from the
  default `/whereis` for workspaces where that slash command is already
  taken by another app. Must include the leading `/`; misuse raises
  `OfficeError(EXIT_ENV_ERROR)`.

## [0.9.1] - 2026-05-03

### Added

- `docs/setup.md` — quick-start walkthrough (default CSV store + stub
  directory works with no env vars or extras) plus a uniform optional-
  features index covering Sheets, DynamoDB, BambooHR, Slack, web map,
  and SSO. BambooHR is presented as one optional extra among many,
  with the `OFFICE_BAMBOOHR_ENABLED` gate documented inline.
- Cross-links from `README.md` and `docs/features/README.md` pointing
  to the new setup page as the entry point.

## [0.9.0] - 2026-05-03

### Changed

- Gate BambooHR directory backend behind `OFFICE_BAMBOOHR_ENABLED` env
  flag (default off). Existing `directory.type: bamboohr` configuration
  silently falls back to the stub directory with a stderr warning until
  the flag is set. All BambooHR code, tests, and the `[bamboohr]` extra
  remain in place — opt in with `OFFICE_BAMBOOHR_ENABLED=1`.

## [Unreleased]

## [0.8.1] - 2026-05-01

### Added

- `CONTRIBUTING.md` — contributor guide (fork, dev loop, conventions, OSS scope).
- `docs/features/` — per-feature deep-dive index plus pages for CLI, BambooHR,
  Slack, web map, effective dates, roles, Sheets, DynamoDB, and bi-directional
  sync.

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

[Unreleased]: https://github.com/agentculture/office-agent/compare/v0.9.1...HEAD
[0.9.1]: https://github.com/agentculture/office-agent/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/agentculture/office-agent/compare/v0.8.1...v0.9.0
[0.8.1]: https://github.com/agentculture/office-agent/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/agentculture/office-agent/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/agentculture/office-agent/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/agentculture/office-agent/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/agentculture/office-agent/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/agentculture/office-agent/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/agentculture/office-agent/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/agentculture/office-agent/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/agentculture/office-agent/compare/v0.0.1...v0.1.0
[0.0.1]: https://github.com/agentculture/office-agent/releases/tag/v0.0.1
