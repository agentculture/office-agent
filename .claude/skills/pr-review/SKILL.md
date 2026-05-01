---
name: pr-review
description: >
  Steward-specific PR workflow: branch, commit, push, PR, wait for Qodo/Copilot,
  triage, fix, reply, resolve. Adds a portability lint (no absolute /home paths,
  no per-user dotfile refs in committed docs), an alignment-delta check when
  CLAUDE.md or culture.yaml change, and greenfield-aware test/version-bump
  steps. Use when: creating PRs in steward, handling review feedback, or the
  user says "create PR", "review comments", "address feedback", "resolve threads".
---

# PR Review — Steward edition

Steward's PRs touch agent prompts, `culture.yaml` configs, and cross-project
guidance. The generic `pr-review` skills don't know that, so they miss two
classes of bugs Steward keeps producing:

- **Path leaks** — committing absolute home-directory paths that work only on
  the author's machine. (PR #1 had four of these.)
- **Per-user config dependencies** — referencing a dotfile under the user's
  home directory in repo guidance, breaking reproducibility for other
  contributors and CI.

This skill specializes Culture's `pr-review` to catch both up front, plus an
alignment-delta step when Steward-affecting files change. The workflow is
encapsulated in `scripts/workflow.sh` — follow that, not a manual checklist.

## Prerequisites

Hard requirements: `gh` (GitHub CLI), `jq`, `bash`, `python3` (stdlib only),
`curl` (used by `pr-status.sh`).

Soft requirement: `PyYAML` is needed **only for suffix mode** of the sibling
`agent-config` skill, where it parses Culture's server manifest. Path mode
and every `pr-review` script work without it. If suffix mode runs without
PyYAML it exits with a clear install hint.

Per-machine paths (sibling-project layout) live in
`.claude/skills.local.yaml`; see the committed `.example` for the schema.

## How to run

`scripts/workflow.sh` is the entry point. Subcommands:

| Command | Purpose |
|---------|---------|
| `workflow.sh lint` | Portability lint on the current diff (staged + unstaged). |
| `workflow.sh poll <PR>` | Fetch and display all review comments. |
| `workflow.sh delta` | Dump each sibling project's `CLAUDE.md` head + `culture.yaml`. |
| `workflow.sh reply <PR>` | Batch reply (JSONL on stdin) and resolve threads. |
| `workflow.sh help` | Print this list. |

The vendored single-comment helpers — `pr-reply.sh`, `pr-status.sh` — live
next to `workflow.sh` and are usable directly when batching isn't appropriate.

## End-to-end flow

```text
git checkout -b <type>/<desc>
# ... edit ...
.claude/skills/pr-review/scripts/workflow.sh lint
git commit -am "..." && git push -u origin <branch>
gh pr create --title "..." --body "..."   # title <70 chars, body signed "- Claude"
sleep 300                                  # wait for Qodo + Copilot
.claude/skills/pr-review/scripts/workflow.sh poll <PR>
# triage; if CLAUDE.md/culture.yaml/.claude/skills changed:
.claude/skills/pr-review/scripts/workflow.sh delta
# fix, re-lint, push
.claude/skills/pr-review/scripts/workflow.sh reply <PR> < replies.jsonl
gh pr checks <PR>
# Wait for human merge — never merge yourself.
```

Branch naming: `fix/<desc>`, `feat/<desc>`, `docs/<desc>`, `skill/<name>`.
Commit/PR signature: `- Claude` (workspace convention). The reply script
auto-appends `- Claude` only if the body isn't already signed, so JSONL
entries can include or omit it.

## Triage rules

For every comment, decide **FIX** or **PUSHBACK** with reasoning.

Default to **FIX** for: portability complaints (always valid for Steward —
recurring bug class), test or doc requests, style nits aligned with workspace
conventions.

Default to **PUSHBACK** for: architecture opinions that conflict with workspace
`CLAUDE.md` or the all-backends rule; greenfield false-positives (e.g. "add
tests" before there's any source — defer to a later PR, don't refuse).

### Alignment-delta rule

If the PR touches `CLAUDE.md`, `culture.yaml`, or anything under
`.claude/skills/`, run `workflow.sh delta` **before** declaring FIX or
PUSHBACK on each comment. The script dumps the head of every sibling
project's `CLAUDE.md` plus the full `culture.yaml`, using `sibling_projects`
from `skills.local.yaml`. Note any sibling that needs a follow-up PR and
mention it in your reply.

## Greenfield-aware steps

The lint and the workflow script are always-on. Stack-specific steps are
conditional and currently no-op (greenfield repo):

```bash
[ -d tests ] && [ -f pyproject.toml ] && uv run pytest tests/ -x -q
[ -f pyproject.toml ] && bump_version_per_project_convention   # see project README
[ -f .markdownlint-cli2.yaml ] && markdownlint-cli2 "$(git diff --name-only --cached '*.md')"
```

Revisit each line as the corresponding stack element actually lands.

## Reply etiquette

Every comment must get a reply — no silent fixes. Always pass `--resolve`
when batch-replying so threads close automatically. Reference the
review-comment IDs in the fix-up commit message. Steward currently has no
SonarCloud integration and isn't a registered mesh agent, so skip the
sonarclaude check and the post-merge IRC ping that Culture's `pr-review`
includes — those will return when Steward joins those systems.
