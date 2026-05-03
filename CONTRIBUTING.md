# Contributing to office-agent

Thanks for your interest. This is a small, focused project — the
contribution flow is light but the conventions matter because the
CLI's public surface ships to PyPI on every merge to `main`.

For the system overview, start with [README.md](./README.md). For
feature deep-dives, see [docs/features/](./docs/features/). For the
stage-by-stage implementation history, see
[docs/architecture.md](./docs/architecture.md).

## Quickstart for contributors

```bash
git clone https://github.com/agentculture/office-agent
cd office-agent
uv sync                                       # install deps
uv run pytest -n auto -q                      # full suite, parallel
uv run office --version
```

For a clean dev environment with every optional extra:

```bash
uv pip install -e '.[sheets,bamboohr,slack,web,sso,dynamo]'
```

## Branch + commit naming

| Prefix            | Use for                                            |
| ----------------- | -------------------------------------------------- |
| `feat/<desc>`     | New user-visible feature.                          |
| `fix/<desc>`      | Bug fix.                                           |
| `docs/<desc>`     | Docs-only changes.                                 |
| `chore/<desc>`    | Tooling, CI, dependency bumps, no behavior change. |
| `refactor/<desc>` | Internal restructure, no behavior change.          |

Commit messages aren't strictly Conventional Commits, but landing
PR commit messages tend to follow `feat:` / `fix:` / `docs:` /
`chore:` / `refactor:` prefixes for searchability in
[CHANGELOG.md](./CHANGELOG.md).

Sign every commit body and PR body with a trailing `- Claude` (or
your name) so the agent-driven PR-review flow can attribute
replies.

## PR contract

Every PR must:

1. **Bump the version** in `pyproject.toml`. The `version-check`
   CI job rejects PRs that don't.

   ```bash
   python3 .claude/skills/version-bump/scripts/bump.py patch     # docs / fixes
   python3 .claude/skills/version-bump/scripts/bump.py minor     # new feature
   python3 .claude/skills/version-bump/scripts/bump.py major     # breaking
   ```

   The script also prepends a `[<version>]` section to
   `CHANGELOG.md` for you.

2. **Pass the lint chain** (CI runs all of these):

   ```bash
   uv run black --check office_cli tests
   uv run isort --check-only office_cli tests
   uv run flake8 office_cli tests
   uv run bandit -c pyproject.toml -r office_cli
   markdownlint-cli2 "**/*.md" "#node_modules" "#.venv"
   ```

3. **Pass the test suite**:

   ```bash
   uv run pytest -n auto -q
   ```

   Coverage threshold is 60% (`fail_under` in `pyproject.toml`).

4. **Update the relevant doc**. If you touch a feature, update the
   matching `docs/features/<feature>.md`. If you touch the CLI
   contract, update `docs/features/cli.md`. If you ship a new
   stage, add a section to `docs/architecture.md`.

5. **Link the issue** the PR addresses. PR descriptions follow the
   template in `.github/PULL_REQUEST_TEMPLATE.md`.

## Optional-extras matrix

When you add a new feature that depends on a third-party library,
follow the lazy-import + optional-extra pattern (see
[Stages 2–8](./docs/architecture.md) for prior art):

1. Add the extra to `pyproject.toml` `[project.optional-dependencies]`:

   ```toml
   [project.optional-dependencies]
   myfeat = ["mylib>=1.0"]
   ```

2. **Lazy-import** the dep inside the runtime module so the
   package loads cleanly without the extra installed:

   ```python
   def use_myfeat():
       try:
           import mylib
       except ImportError as err:
           raise OfficeError(
               code=EXIT_ENV_ERROR,
               message="mylib is not installed",
               remediation="install the myfeat extra: uv tool install 'office-cli[myfeat]'",
           ) from err
       ...
   ```

3. **Mirror the extra in the dev dep group** so CI exercises the
   path:

   ```toml
   [dependency-groups]
   dev = [
       ...,
       "mylib>=1.0",
   ]
   ```

4. **Test with a hand-rolled fake**, not a real-API mock library.
   We don't take heavy test deps (no `moto`, no `responses`); the
   `FakeSheetsClient` / `FakeBambooHRClient` / `FakeDynamoClient`
   pattern is the convention.

## Code review

PRs go through three reviewers:

1. **Qodo** (free Code Review bot) — produces a walkthrough +
   inline correctness/rule comments.
2. **Copilot** (GitHub Copilot Code Review) — inline comments.
3. **SonarCloud** — quality gate + new-issue list. Must pass.

Use the in-repo `pr-review` skill to drive the loop:

```bash
.claude/skills/pr-review/scripts/workflow.sh poll <PR>
.claude/skills/pr-review/scripts/workflow.sh reply <PR> --resolve < replies.jsonl
```

Sonar findings that the rule's premise doesn't fit can be accepted
with rationale via `.claude/skills/sonarclaude/scripts/sonar.sh
accept`. Don't dismiss silently — the rationale lives forever in
the SonarCloud history and helps future maintainers.

## Skills convention

Vendored skills live under `.claude/skills/<name>/` and ship with:

1. `SKILL.md` (frontmatter `name` matches the directory name).
2. A sibling `scripts/` directory.
3. **No path dependencies** on external checkouts — skills must
   work on a fresh `git clone`.

`steward doctor . --scope self` enforces all three rules. If you
add a new skill, run it.

## Reporting issues

- **Bug**: open an issue using
  [`bug_report.md`](./.github/ISSUE_TEMPLATE/bug_report.md).
- **Feature**: open an issue using
  [`feature_request.md`](./.github/ISSUE_TEMPLATE/feature_request.md).
- **Security**: see [SECURITY.md](./SECURITY.md). Don't open a
  public issue.

## Code of Conduct

Participation is governed by the
[Contributor Covenant](./CODE_OF_CONDUCT.md). Reports of
unacceptable behavior go to <ori@agentculture.org>.

## License

By contributing, you agree your contribution is licensed under
the [MIT License](./LICENSE).
