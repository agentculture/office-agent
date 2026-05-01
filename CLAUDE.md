# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

Pre-bootstrap. No source code yet — only this file plus `LICENSE` and `.gitignore`. The full v1 design lives in two GitHub issues — read them before doing any non-trivial work:

- [agentculture/office-agent#2](https://github.com/agentculture/office-agent/issues/2) — Bootstrap office-cli (0.0.1) from the AgentCulture sibling pattern. End-to-end recipe with exact files to fetch from `agentculture/steward` and `agentculture/afi-cli`.
- [agentculture/office-agent#1](https://github.com/agentculture/office-agent/issues/1) — v1 floor-plan seating system. Splits work between human (Inkscape SVG tracing) and agent (backend, search, Slack `/whereis`).

Issue #2 is the next step. Issue #1 is the product on top of it.

## What this is

Office — a CLI and backend for managing seat assignments and meeting rooms across office floor plans. Floors are hand-traced SVGs with stable, conformant IDs; assignments are stored in a Google Sheet (v1) or DynamoDB (v2); people are pulled live from BambooHR (never stored locally). Slack `/whereis @user` is the primary user surface; a search-first web map is the secondary one.

## Naming surfaces (don't conflate)

The bootstrap issue uses several similar-looking identifiers across surfaces — mixing them silently breaks imports or PyPI:

| Surface             | Value         | Notes                                                  |
| ------------------- | ------------- | ------------------------------------------------------ |
| GitHub repo         | `office-agent`| May be renamed; centralize references                  |
| PyPI distribution   | `office-cli`  | Used in `pyproject.toml` `name`, CI, Trusted Publisher |
| Python package      | `office_cli`  | Underscore — Python imports cannot contain hyphens     |
| CLI binary          | `office`      | `[project.scripts]` entry point                        |
| Error class prefix  | `Office`      | `OfficeError`, not `Office_cliError`                   |

Do **not** blanket-replace `tipalti` or `steward` when porting from sibling repos — substitute per-surface using the table above. Some `steward` references in CI workflows point at the upstream skill source (`raw.githubusercontent.com/agentculture/steward/main/...`) and must stay as-is.

## SVG ID contract (the human deliverable)

Floor SVGs in `floors/` are the integration boundary between Ori's Inkscape work and the agent's backend. The backend reads `id` attributes off `<rect>` and `<polygon>` elements; nothing else.

| Element                         | ID format                       | Example          |
| ------------------------------- | ------------------------------- | ---------------- |
| Open-space desk                 | `<floor>-<cluster>-<NN>`        | `5-T-01`         |
| Named room (architect's legend) | `<architect-id>` verbatim       | `5.18`           |
| Phone/zoom room as a seat       | open-space pattern              | `5-Z-04`         |
| Cluster boundary (optional)     | `cluster-<floor>-<letter>`      | `cluster-5-T`    |

Rules: IDs unique within a file; floor number first; cluster letter uppercase; sequence zero-padded to 2 digits; `class="seat"` on desk rects, `class="room"` on room polygons; **no person data** in the SVG (assignments live in the datastore). Save as **Plain SVG**, `viewBox="0 0 1920 1080"`, background image embedded.

`data/offices.yaml` declares cluster capacity per floor; the build should warn if the count of seat IDs in the SVG doesn't match.

## Conventions (incoming, from the sibling pattern)

Once issue #2 lands, the project will use:

- **uv** for dependency and tool management; **hatchling** as the build backend.
- **pytest-xdist** (`uv run pytest -n auto -v`); flake8 / black / isort / bandit; markdownlint-cli2 with a repo-local `.markdownlint-cli2.yaml`.
- **PyPI Trusted Publishing** via `.github/workflows/publish.yml`; `version-check` CI job enforces a version bump on every PR against `origin/main`.
- **Skills** under `.claude/skills/<name>/` — each must have `SKILL.md` and a sibling `scripts/` directory, with no path dependencies on external checkouts. Required skills: `version-bump`, `pr-review`, `run-tests`, `gh-issues`. `steward doctor . --scope self` enforces the convention.
- **afi-cli** scaffold under `office_cli/cli/` — `_errors.py`, `_output.py`, and `_commands/{learn,explain,whoami}.py` follow a stable contract; copy verbatim with token substitution rather than rewriting.

## Architectural guardrails (from issue #1)

Lessons paid for in advance — don't relitigate without a reason:

- **BambooHR is the source of truth for people.** Never store name/email/role/photo locally; pull on request, cache 5 minutes. Offboarding in BambooHR must auto-vacate the seat without anyone editing the Sheet — this is the killer feature, verify it end-to-end.
- **The Google Sheet is the CMS.** Don't build an in-app editor for assignments. Don't build an in-app SVG editor either — Inkscape is the editor for layouts.
- **Audit log is append-only.** Seat changes never overwrite history; "who used to sit at 5-T-01?" must return chronological history.
- **Multi-office from day one.** No hardcoded `tlv`. Adding a floor = drop SVG + add `data/offices.yaml` entry, no code change.
- **Future-dated assignments**: the data model carries `effective_from` / `effective_until` even if the UI ships without it. `?asOf=YYYY-MM-DD` renders the map as of that date.
- **`hidden=TRUE`** rows show as "occupied (private)" to viewers; full details only to the `editor` / `planning` roles.
- **Out of scope for v1**: hot-desking / desk booking, native mobile app, visitor/badge/sensor integration, in-app SVG editor.

## When picking up issue #2

The issue is written to be runnable on any machine — it does not assume sibling checkouts at `../steward` or `../afi-cli`. Fetch from GitHub raw URLs or install the published CLIs (`uv tool install steward-cli afi-cli`). Work on a single feature branch (`bootstrap/sibling-pattern`), open one PR, then run the `pr-review` skill.

Three post-merge tasks must be called out in the PR body for the human (they require UI clicks Claude can't do): configure PyPI + TestPyPI Trusted Publishers for `office-cli`, create the `pypi` and `testpypi` GitHub Environments, and enable branch protection requiring `tests` and `version-check` on `main`.
