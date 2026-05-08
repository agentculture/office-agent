# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Office — a CLI and backend for managing seat assignments and meeting rooms across office floor plans. Floors are hand-traced SVGs with stable, conformant IDs; assignments are stored in a Google Sheet (v1) or DynamoDB (v2); people are pulled live from BambooHR (never stored locally). Slack `/whereis @user` is the primary user surface; a search-first web map is the secondary one.

The full v1 design lives in two GitHub issues — read them before doing any non-trivial work:

- [agentculture/office-agent#2](https://github.com/agentculture/office-agent/issues/2) — Bootstrap office-cli (0.0.1) from the AgentCulture sibling pattern. **Implemented in this repo.**
- [agentculture/office-agent#1](https://github.com/agentculture/office-agent/issues/1) — v1 floor-plan seating system. The product on top of this scaffold.

## Naming surfaces (don't conflate)

The project uses several similar-looking identifiers across surfaces — mixing them silently breaks imports or PyPI:

| Surface             | Value         | Notes                                                  |
| ------------------- | ------------- | ------------------------------------------------------ |
| GitHub repo         | `office-agent`| May be renamed; centralize references                  |
| PyPI distribution   | `office-cli`  | Used in `pyproject.toml` `name`, CI, Trusted Publisher |
| Python package      | `office_cli`  | Underscore — Python imports cannot contain hyphens     |
| CLI binary          | `office`      | `[project.scripts]` entry point                        |
| Error class prefix  | `Office`      | `OfficeError`, not `Office_cliError`                   |

Do **not** blanket-replace `tipalti` or `steward` when porting from sibling repos — substitute per-surface using the table above. Some `steward` references in CI workflows or skill scripts point at the upstream source (`raw.githubusercontent.com/agentculture/steward/main/...`) and must stay as-is.

## Project shape

```text
office-agent/
├── office_cli/                  # Python package (import name)
│   ├── __init__.py              # __version__ via importlib.metadata("office-cli")
│   ├── __main__.py              # `python -m office_cli`
│   ├── cli/
│   │   ├── __init__.py          # argparse main(); _ArgumentParser override
│   │   ├── _errors.py           # OfficeError + EXIT_SUCCESS / _USER_ERROR / _ENV_ERROR / _INTERNAL_ERROR
│   │   ├── _output.py           # emit_result / emit_error / emit_diagnostic
│   │   └── _commands/           # learn, explain, whoami, floors, seats, whereis
│   ├── _config.py               # resolve_data_dir() / --data-dir / OFFICE_DATA_DIR
│   ├── _dates.py                # parse_iso_date / today_iso_date / is_effective (Stage 6)
│   ├── _roles.py                # RolesConfig / role_for_email / is_full_access (Stage 7)
│   ├── offices/                 # offices.yaml loader + Office/Floor/Cluster/Room
│   ├── floors/                  # SVG parse + ID contract + validator
│   ├── seats/                   # AssignmentStore + Csv/Sheets/Dynamo stores + AuditLog + SeatService
│   │                            # Stage 8: bi-directional sync via `office seats sync`
│   ├── people/                  # Employee + EmployeeDirectory (Stub + BambooHR backends)
│   ├── slack/                   # `/whereis` Bolt app + Socket Mode runner (optional [slack] extra)
│   ├── server/                  # FastAPI seat-map server + vanilla-JS frontend (optional [web] extra)
│   │                            # Stage 7: SSO + role-aware redaction (optional [sso] extra)
│   └── explain/                 # Markdown catalog for `office explain <path>`
├── data/offices.yaml            # office / floor / cluster topology
├── floors/                      # human-traced floor SVGs
├── seats/                       # assignments.csv + audit-log.csv (git-ignored)
├── docs/                        # architecture.md, tracing-guide.md (TBD)
├── tests/                       # pytest suite incl. fixtures/ for offices+floors
├── .github/workflows/           # tests.yml, publish.yml
├── .claude/skills/              # vendored from agentculture/steward
└── pyproject.toml               # SSoT for version; [project.scripts] entry
```

## Build / test / publish

```bash
uv sync                           # install runtime + dev deps
uv run pytest -n auto -v          # full suite, parallel
uv run office --version           # 0.8.0
uv run office learn               # agent affordance
uv run office whoami              # auth probe stub
uv run office floors validate floors/tlv-floor-5.svg
uv run office seats list --vacant
uv run office whereis alice@example.com
uv run python -m office_cli       # equivalent to `office`

uv run black --check office_cli tests
uv run isort --check-only office_cli tests
uv run flake8 office_cli tests
uv run bandit -c pyproject.toml -r office_cli
markdownlint-cli2 "**/*.md" "#node_modules"

steward doctor . --scope self     # portability + skills convention check

uv build                          # produce wheel + sdist
```

PyPI publishing happens automatically via `.github/workflows/publish.yml`
on push to `main` (Trusted Publishing — no API tokens). PRs publish a
`<version>.dev<run>` to TestPyPI for smoke-testing.

**Every PR must bump `pyproject.toml` `version`** — the `version-check` CI
job fails otherwise. Use the `version-bump` skill:

```bash
python3 .claude/skills/version-bump/scripts/bump.py patch
```

## Conventions

- **uv** for dependency and tool management; **hatchling** as the build backend.
- **pytest-xdist** (`uv run pytest -n auto -v`); coverage via `pytest-cov`; `fail_under = 60`.
- **black** + **isort** + **flake8** + **bandit** configured in `pyproject.toml` and `.flake8`.
- **markdownlint-cli2** with repo-local `.markdownlint-cli2.yaml`.
- **PyPI Trusted Publishing** via `.github/workflows/publish.yml`. The `version-check` CI job enforces a per-PR version bump against `origin/main`.
- **Keep a Changelog** format in `CHANGELOG.md`; the `version-bump` skill prepends entries automatically.

## SonarCloud guidance

Sonar **S5332** ("HTTP URL — should use HTTPS") flags the SVG namespace
URI in `office_cli/floors/_doctor.py`:

```python
ET.register_namespace("", "http://www.w3.org/2000/svg")
```

This is a **known false positive**. The string is the W3C **XML
namespace identifier** for SVG — not a fetched URL. The literal
`http://www.w3.org/2000/svg` is the value SVG renderers (browsers,
xmllint, Inkscape) recognize; rewriting it to `https://...` produces
a different, unrecognized namespace. Removing the
`register_namespace` call makes ElementTree emit
`<ns0:svg xmlns:ns0="...">` at the root, which browsers reject as
"not a valid SVG document" — confirmed via the floor-5 walkthrough
(PR #50 review removed it; PR #53 restored it). Mark the hotspot
SAFE on Sonar with this rationale; do **not** "fix" it in code.

## Skills convention

`.claude/skills/<name>/` — each skill must have:

1. `SKILL.md` (frontmatter `name` matches directory name)
2. A sibling `scripts/` directory with the skill's executables
3. No path dependencies on external checkouts (skill scripts must work on a fresh `git clone`)

`steward doctor . --scope self` enforces all three rules.

Vendored skills (from `agentculture/steward`):

- **Required** (CI- or contract-load-bearing): `version-bump`, `pr-review`, `run-tests`, `gh-issues`
- **Recommended**: `pypi-maintainer`, `notebooklm`, `sonarclaude`

Per-machine overrides live in `.claude/skills.local.yaml` (git-ignored;
`.claude/skills.local.yaml.example` is the template).

## SVG ID contract (issue #1 — the human deliverable)

Floor SVGs in `floors/` are the integration boundary between Ori's Inkscape work and the agent's backend. The backend reads `id` attributes off `<rect>` and `<polygon>` elements; nothing else.

| Element                         | ID format                       | Example          |
| ------------------------------- | ------------------------------- | ---------------- |
| Open-space desk                 | `<floor>-<cluster>-<NN>`        | `5-T-01`         |
| Named room (architect's legend) | `<architect-id>` verbatim       | `5.18`           |
| Phone/zoom room as a seat       | open-space pattern              | `5-Z-04`         |
| Cluster boundary (optional)     | `cluster-<floor>-<letter>`      | `cluster-5-T`    |

Rules: IDs unique within a file; floor number first; cluster letter uppercase; sequence zero-padded to 2 digits; `class="seat"` on desk rects, `class="room"` on room polygons; **no person data** in the SVG (assignments live in the datastore). Save as **Plain SVG**, `viewBox="0 0 1920 1080"`, background image embedded.

`data/offices.yaml` declares cluster capacity per floor; the build should warn if the count of seat IDs in the SVG doesn't match.

## Architectural guardrails (issue #1)

Lessons paid for in advance — don't relitigate without a reason:

- **BambooHR is the source of truth for people.** Never store name/email/role/photo locally; pull on request, cache 5 minutes. Offboarding in BambooHR must auto-vacate the seat without anyone editing the Sheet — this is the killer feature, verify it end-to-end.
- **The Google Sheet is the CMS.** Don't build an in-app editor for assignments. Don't build an in-app SVG editor either — Inkscape is the editor for layouts. Stage 8 adds DynamoDB as a second runtime backend, but Sheets stays a first-class option — `office seats migrate --from X --to Y` (one-shot) and `office seats sync --primary {sheets,dynamo}` (bi-directional last-write-wins) keep them interoperable.
- **Audit log is append-only.** Seat changes never overwrite history; "who used to sit at 5-T-01?" must return chronological history.
- **Multi-office from day one.** No hardcoded `tlv`. Adding a floor = drop SVG + add `data/offices.yaml` entry, no code change.
- **Future-dated assignments**: the data model carries `effective_from` / `effective_until` and Stage 6 enforces them at the service layer. `office seats assign --from / --until`, `office whereis --as-of`, `office seats list --as-of`, `?asOf=YYYY-MM-DD` on the web map, and a trailing `YYYY-MM-DD` token on Slack `/whereis` all flow through the same window check. `effective_*` is stored as `YYYY-MM-DD` (date precision, no time); `last_updated` and audit timestamps stay full ISO-8601.
- **`hidden=TRUE`** rows show as "occupied (private)" to viewers; full details only to the `editor` / `planning` roles. Stage 7 enforces this end-to-end. Roles map lives in `data/offices.yaml` under `roles:`. The CLI is operator-only and unrestricted (`role=None` → no redaction). Web SSO is opt-in via `OIDC_*`/`SESSION_SECRET` env vars; when unset, the server runs in auth-disabled mode (local dev). Tests use `X-Test-Role: viewer|editor|planning` to drive role-aware behavior; this header is **only** honored when OIDC is disabled.
- **Out of scope for v1**: hot-desking / desk booking, native mobile app, visitor/badge/sensor integration, in-app SVG editor.

## Picking up issue #1

The scaffold is in place. New verbs land under `office_cli/cli/_commands/`
following the same pattern as `whoami` / `learn`: each module exports
`register(sub)` and a `cmd_<name>(args)` handler returning an `int` exit
code. Add a corresponding `office_cli/explain/catalog.py` entry and a
test file under `tests/`. Bump `pyproject.toml` and `CHANGELOG.md` per
PR (or run the `version-bump` skill).
