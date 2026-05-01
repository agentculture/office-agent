---
name: gh-issues
description: >
  Fetch GitHub issues with full body and comments. Use when checking issues,
  reviewing bug reports, or the user says "check issues", "fetch issues",
  "issue #N", or references GitHub issue numbers.
triggers:
  - check issues
  - fetch issues
  - issue #
  - github issues
  - verify issues
---

# GitHub Issues Skill

Fetch one or more GitHub issues with full body text and all comments.

## Usage

### Single issue

```bash
bash .claude/skills/gh-issues/scripts/gh-issues.sh 191
```

### Range

```bash
bash .claude/skills/gh-issues/scripts/gh-issues.sh 191-197
```

### Specific list

```bash
bash .claude/skills/gh-issues/scripts/gh-issues.sh 191 195 197
```

### Explicit repo

```bash
bash .claude/skills/gh-issues/scripts/gh-issues.sh --repo owner/repo 42-50
```

Output is JSON per issue with: number, title, state, labels, body, and comments array.
