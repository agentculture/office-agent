# Changelog

All notable changes to this project will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/). This project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
