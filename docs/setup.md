# Setup

A walkthrough from a fresh checkout to a working `office` CLI in under
five minutes, with every backend, surface, and integration presented as
**optional**. The default install runs against a local CSV store and a
no-op stub directory — no Google account, no AWS, no BambooHR token.

For the design background and stage-by-stage history see
[`architecture.md`](./architecture.md). For per-feature deep dives see the
[feature index](./features/README.md).

## Prerequisites

- **uv** — the only hard dep for development; install via
  `curl -LsSf https://astral.sh/uv/install.sh | sh`
  ([docs](https://docs.astral.sh/uv/getting-started/installation/)).
- **Python 3.12** — `uv sync` provisions an isolated interpreter; no
  system Python required.
- **git** — to clone the repo.

## Quick start (defaults: CSV store + stub directory)

```bash
git clone https://github.com/agentculture/office-agent.git
cd office-agent
uv sync                                            # install runtime + dev deps
uv run office --version                            # 0.9.1
uv run office floors validate floors/tlv-floor-5.svg
uv run office seats list --vacant
uv run office whereis alice@example.com
```

This works with **no env vars and no extras**:

- Storage defaults to CSV under `seats/assignments.csv` +
  `seats/audit-log.csv` (git-ignored).
- People directory defaults to `StubDirectory`, which trusts every email
  it receives.
- Floor SVGs and `data/offices.yaml` are read from the current working
  directory; override with `--data-dir DIR` or `OFFICE_DATA_DIR=DIR`.

End-users typically install the published wheel instead:

```bash
uv tool install office-cli                         # latest from PyPI
office --version
```

## Optional features (install only what you need)

Every feature below is opt-in. The package imports cleanly without any
of these extras — install just the ones you intend to use.

| Feature                                                    | Extra        | Activated by                                                          | Deep dive                                |
| ---------------------------------------------------------- | ------------ | --------------------------------------------------------------------- | ---------------------------------------- |
| [Google Sheets store](./features/sheets.md)                | `[sheets]`   | `OFFICE_STORE=sheets` + `OFFICE_SHEETS_ID` + `OFFICE_SHEETS_SA`       | [`sheets.md`](./features/sheets.md)      |
| [DynamoDB store](./features/dynamodb.md)                   | `[dynamo]`   | `OFFICE_STORE=dynamo` + `OFFICE_DYNAMO_*`                             | [`dynamodb.md`](./features/dynamodb.md)  |
| [BambooHR directory + auto-vacate](./features/bamboohr.md) | `[bamboohr]` | `OFFICE_BAMBOOHR_ENABLED=1` **(gate)** + `OFFICE_DIRECTORY=bamboohr`  | [`bamboohr.md`](./features/bamboohr.md)  |
| [Slack `/whereis`](./features/slack.md)                    | `[slack]`    | `SLACK_BOT_TOKEN` + `SLACK_APP_TOKEN`; run `office slack-serve`       | [`slack.md`](./features/slack.md)        |
| [Web map server](./features/web-map.md)                    | `[web]`      | run `office serve`                                                    | [`web-map.md`](./features/web-map.md)    |
| [SSO + roles for the web map](./features/roles.md)         | `[web,sso]`  | all of `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_REDIRECT_URL`, `SESSION_SECRET` | [`roles.md`](./features/roles.md) |

Each entry below is the **minimum** to bring the feature up. The deep-dive
pages cover provider-side setup (GCP service accounts, Slack app config,
IdP registration), YAML schemas, and operational notes.

### Google Sheets store (optional)

```bash
uv tool install 'office-cli[sheets]'
export OFFICE_STORE=sheets
export OFFICE_SHEETS_ID=1abc...                    # spreadsheet ID from URL
export OFFICE_SHEETS_SA=/path/to/service-account.json
```

The service-account JSON is **never** committed. Full GCP setup
checklist: [`features/sheets.md`](./features/sheets.md#operator-setup-checklist).

### DynamoDB store (optional)

```bash
uv tool install 'office-cli[dynamo]'
export OFFICE_STORE=dynamo
export OFFICE_DYNAMO_ASSIGNMENTS=office-assignments
export OFFICE_DYNAMO_AUDIT=office-audit-log
export OFFICE_DYNAMO_REGION=us-east-1
```

AWS credentials follow the standard chain (`AWS_PROFILE`, IAM role, etc.)
— never in YAML. Full schema and key design: [`features/dynamodb.md`](./features/dynamodb.md).

If you operate both Sheets and Dynamo, the sync verbs keep them
in agreement: see [`features/sync.md`](./features/sync.md).

### BambooHR directory + auto-vacate (optional)

The BambooHR backend is **gated off by default**. Without
`OFFICE_BAMBOOHR_ENABLED=1`, the seat service falls back to the stub
directory and prints a one-line warning to stderr — even when
`OFFICE_DIRECTORY=bamboohr` is set. This is intentional so that pulling
the wheel into a new environment doesn't accidentally start hitting
BambooHR with stale credentials.

```bash
uv tool install 'office-cli[bamboohr]'
export OFFICE_BAMBOOHR_ENABLED=1                   # required: opt in to the gated feature
export OFFICE_DIRECTORY=bamboohr
export BAMBOOHR_SUBDOMAIN=tipalti
export BAMBOOHR_API_TOKEN=...                      # secret — env-only, never in YAML
```

The gate accepts `1`, `true`, `yes`, `on` (case-insensitive) to enable
and `0`, `false`, `no`, `off` (or unset) to disable. Anything else
raises an `OfficeError` so typos fail loudly.

The auto-vacate contract — "a seat assigned to an offboarded employee
renders as vacant automatically, with no Sheet edit" — is the killer
feature. Full rationale, TTL cache, and fail-open semantics:
[`features/bamboohr.md`](./features/bamboohr.md).

### Slack `/whereis` (optional)

```bash
uv tool install 'office-cli[slack]'
export SLACK_BOT_TOKEN=xoxb-...
export SLACK_APP_TOKEN=xapp-...
office slack-serve
```

Requires a Slack app with `commands`, `users:read.email`, `chat:write`
scopes and Socket Mode enabled. Full app-side checklist:
[`features/slack.md`](./features/slack.md).

### Web map server (optional)

```bash
uv tool install 'office-cli[web]'
office serve                                       # localhost:8000
office serve --host 0.0.0.0 --port 8080            # bind explicitly
```

Layer SSO on top with `[sso]` (next section). Full server config:
[`features/web-map.md`](./features/web-map.md).

### SSO + roles for the web map (optional)

```bash
uv tool install 'office-cli[web,sso]'
export OIDC_ISSUER=https://your-idp.example.com
export OIDC_CLIENT_ID=office-agent
export OIDC_CLIENT_SECRET=...
export OIDC_REDIRECT_URL=https://office.example.com/auth/callback
export SESSION_SECRET=$(openssl rand -hex 32)
office serve --port 8000
```

All five env vars must be set together; partial config raises
`OfficeError(EXIT_ENV_ERROR)` so misconfigurations fail fast. When the
`OIDC_*` vars are absent the server runs in auth-disabled mode (local
dev). Full IdP-side checklist and the role map under
`data/offices.yaml`: [`features/roles.md`](./features/roles.md).

## Verification

Run the smoke commands from the [Quick start](#quick-start-defaults-csv-store--stub-directory)
and confirm exit codes are 0. Then run the test suite:

```bash
uv run pytest -n auto -v                           # ~300 tests, parallel
```

For the full lint / publish loop (black, isort, flake8, bandit,
markdownlint, `uv build`), see the **Build / test / publish** block in
[`CLAUDE.md`](../CLAUDE.md#build--test--publish).

## Where to go next

- [`architecture.md`](./architecture.md) — the v1 design spec, including
  the SVG ID contract and stage-by-stage implementation history.
- [`features/README.md`](./features/README.md) — index of per-feature
  deep dives.
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md) — fork → branch → PR loop,
  required version bump per PR, skill conventions.
