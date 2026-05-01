# Changelog

All notable changes to this project will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/). This project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/agentculture/office-agent/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/agentculture/office-agent/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/agentculture/office-agent/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/agentculture/office-agent/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/agentculture/office-agent/compare/v0.0.1...v0.1.0
[0.0.1]: https://github.com/agentculture/office-agent/releases/tag/v0.0.1
