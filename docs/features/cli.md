# Agent-first CLI

## What it is

`office` is the command-line entry point and the canonical public
surface of the system. Every other surface — Slack, the web map,
the migration / sync verbs — sits on top of the same
`SeatService`. A human operator can drive the whole product through
the CLI; an agent (Claude, etc.) can drive it just as well because
the CLI is **self-documenting** and **JSON-emitting**.

## Why

The product was designed agent-first. That meant two contracts the
CLI must honor:

- **Self-teaching**: `office learn` returns a comprehensive prompt
  describing every verb, exit-code policy, and JSON shape — agents
  read it once and don't need a separate manual.
- **Structured I/O**: every command accepts `--json` and emits a
  predictable shape. Errors are structured `{code, message,
  remediation}` objects, never bare tracebacks.

You can drop the operator entirely and let an agent do seating ops.
That's the design — "you can just work with Claude without any
interface."

## Install

```bash
uv tool install office-cli
office --version       # 0.8.x
```

Optional extras pull in surface-specific dependencies:

| Extra                  | Adds                               | Used by                                 |
| ---------------------- | ---------------------------------- | --------------------------------------- |
| `office-cli[sheets]`   | `gspread`                          | [Sheets backend](./sheets.md)           |
| `office-cli[bamboohr]` | `requests`                         | [BambooHR + auto-vacate](./bamboohr.md) |
| `office-cli[slack]`    | `slack-bolt`, `slack-sdk`          | [Slack `/whereis`](./slack.md)          |
| `office-cli[web]`      | `fastapi`, `uvicorn`               | [Web map](./web-map.md)                 |
| `office-cli[sso]`      | `authlib`, `itsdangerous`, `httpx` | [SSO + roles](./roles.md)               |
| `office-cli[dynamo]`   | `boto3`                            | [DynamoDB backend](./dynamodb.md)       |

The package imports cleanly without any of the extras — features
that need a missing dep raise `OfficeError(EXIT_ENV_ERROR)` with a
clear `pip install office-cli[<extra>]` remediation.

## Use

### Self-teaching surface

```bash
office learn                          # the full prompt every agent should read
office explain seats                  # markdown docs for any verb path
office explain seats assign
office whoami --json                  # auth probe
```

### Floor + seat operations

```bash
office floors list --json
office floors validate floors/tlv-floor-5.svg

office seats list                     # operator default — unrestricted
office seats list --vacant
office seats list --as-of 2026-07-15  # Stage 6 — see effective-dates.md
office seats list --json --occupied

office seats assign 5-T-01 alice@example.com
office seats assign 5-T-01 alice@example.com --hidden --note "ergonomic"
office seats assign 5-T-01 alice@example.com --from 2026-07-01 --until 2026-12-31

office seats unassign 5-T-01
office seats move alice@example.com 5-T-02
office seats history 5-T-01 --json
```

### Look-ups

```bash
office whereis alice@example.com
office whereis alice@example.com --as-of 2026-07-15 --json
```

### Long-running services

```bash
office serve --port 8000 --data-dir tests/fixtures      # web map
office slack-serve                                       # Slack /whereis listener
```

### Cross-store ops

```bash
office seats migrate --from sheets --to dynamo --dry-run
office seats migrate --from sheets --to dynamo
office seats sync --primary sheets                       # bi-directional
```

## How it works

### Module shape

| Module                       | Role                                                                         |
| ---------------------------- | ---------------------------------------------------------------------------- |
| `office_cli/cli/__init__.py` | `main()` — argparse top-level; dispatch to verb handlers; structured exit.   |
| `office_cli/cli/_errors.py`  | `OfficeError` + `EXIT_SUCCESS`/`_USER_ERROR`/`_ENV_ERROR`/`_INTERNAL_ERROR`. |
| `office_cli/cli/_output.py`  | `emit_result` / `emit_error` / `emit_diagnostic` — `--json` aware.           |
| `office_cli/cli/_commands/`  | One module per verb. Each exports `register(sub)` + `cmd_<name>(args)`.      |

### Exit-code policy

| Code | Meaning                                                            |
| ---- | ------------------------------------------------------------------ |
| 0    | Success.                                                           |
| 1    | User-input error (bad flag, bad path, missing required arg).       |
| 2    | Environment / setup error (missing pip extra, missing env var, …). |
| 3    | Internal error (unexpected exception, classified separately).      |
| 4+   | Reserved.                                                          |

Every failure path raises `OfficeError(code=…, message=…, remediation=…)`.
The CLI dispatcher catches it and:

- Prints `error: <message>\nhint: <remediation>` to stderr.
- In `--json` mode, prints `{"code": …, "message": …, "remediation": …}`.
- Exits with `code`.

No traceback ever leaks. Agents can branch on code; operators read
the hint.

### JSON shape

Every verb that produces output supports `--json`. Examples:

```jsonc
// office seats list --json
{
  "seats": [
    { "seat_id": "5-T-01", "floor": "tlv-floor-5",
      "employee_email": "alice@example.com", "hidden": false,
      "redacted": false, "effective_from": "2026-05-01",
      "effective_until": null, ...}
  ]
}

// office whereis alice@x --json
{ "email": "alice@x", "assignment": { "seat_id": "5-T-01", ... } }

// Error
{ "code": 1, "message": "unknown seat: 9-Q-99",
  "remediation": "run: office seats list to see the known seat IDs" }
```

### Data resolution

`office` looks for `data/offices.yaml`, `floors/`, and `seats/`
in this order:

1. `--data-dir DIR` flag.
2. `OFFICE_DATA_DIR` env var.
3. Current working directory.

The chosen directory is used by the storage / directory / role
resolvers. See [Sheets](./sheets.md), [BambooHR](./bamboohr.md), and
[Roles](./roles.md) for the per-feature config.

## Limits + roadmap

- **No remote-shell mode** — the CLI runs locally; an agent that
  drives it must SSH or run it as a subprocess. A future `office
  serve --rpc` could expose verbs over HTTP, but isn't on the v1
  roadmap.
- **No tab-completion file shipped** — argparse generates `--help`
  for everything, but `bash`/`zsh` completion would be a nice add.
- **No per-verb auth gate** — operators who can run the CLI have
  full access. SSO + roles only gate the **web** + **Slack**
  surfaces. The CLI is operator-only by design.

## Related

- [Architecture stages history](../architecture.md)
- [SSO + roles](./roles.md) — how viewer / editor / planning gating
  works on the web + Slack surfaces (CLI stays unrestricted).
- [Effective-date windows](./effective-dates.md) — `--from` /
  `--until` / `--as-of` semantics shared with web + Slack.
