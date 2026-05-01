---
name: notebooklm
description: >
  Generate GitHub links to repo documentation for NotebookLM ingestion.
  Use when: the user wants to create a NotebookLM notebook about a project,
  needs doc links for a repo, or says "notebooklm", "notebook sources",
  "get repo sources", or "doc links".
---

# NotebookLM — Repo Source Links

Generate GitHub blob URLs for all documentation in the current repo, ready to paste into Google NotebookLM as sources.

## When to Use

- Creating a NotebookLM notebook about a project
- Gathering all doc links for a repo
- Exporting documentation URLs for any external tool

## Usage

```bash
# Categorized output (default)
bash .claude/skills/notebooklm/scripts/get-repo-sources.sh

# Plain URLs only (for copy-paste)
bash .claude/skills/notebooklm/scripts/get-repo-sources.sh --plain

# Include plans and specs
bash .claude/skills/notebooklm/scripts/get-repo-sources.sh --all

# Override branch
bash .claude/skills/notebooklm/scripts/get-repo-sources.sh --branch develop
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--all` | off | Include plans, specs, and changelogs |
| `--plain` | off | Output only URLs, one per line (no headers) |
| `--branch NAME` | auto-detect | Override the git branch used in URLs |

## Requirements

- Must be run inside a git repository with a GitHub remote
- `git` CLI available
