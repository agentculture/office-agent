# office

Agent-first CLI for managing seat assignments and meeting rooms across
office floor plans. Floor layouts are hand-traced SVGs; people come from
BambooHR; assignments live in a Google Sheet (v1) or DynamoDB (v2). The
CLI exposes the same operations as the Slack `/whereis` command and the
web map.

> **Status — v0.4.0.** Stages 1–4 of the v1 seating system are in:
> floor SVG parser/validator, CSV / Google Sheets-backed assignment
> store with append-only audit log, BambooHR-backed `EmployeeDirectory`
> with the auto-vacate killer feature, CLI verbs (`floors`, `seats`,
> `whereis`), and a Slack `/whereis` slash-command listener. The web
> map and remaining stages land on top of the same `office_cli.seats`
> service. See
> [issue #1](https://github.com/agentculture/office-agent/issues/1).

## Naming surfaces

`office` uses three different identifiers across packaging surfaces. Mind
the split — do not blanket-replace one token across the codebase.

| Surface             | Value         |
| ------------------- | ------------- |
| GitHub repo         | `agentculture/office-agent` |
| PyPI distribution   | `office-cli`  |
| Python package      | `office_cli`  |
| CLI binary          | `office`      |
| Error class prefix  | `Office`      |

## Install

```bash
uv tool install office-cli
office --version
```

## Use

```bash
office learn                                    # self-teaching prompt
office explain seats                            # markdown docs for any verb
office whoami --json                            # auth probe (stub)

# v0.1.0 seating verbs:
office floors list --json
office floors validate floors/tlv-floor-5.svg
office seats list --vacant
office seats assign 5-T-01 alice@example.com
office seats move alice@example.com 5-T-02
office seats history 5-T-01 --json
office whereis alice@example.com
```

`office` reads `data/offices.yaml`, `floors/`, and `seats/` from the
current working directory. Override with `--data-dir DIR` or
`OFFICE_DATA_DIR=DIR`.

### Storage backend

`office` defaults to CSV-backed storage under `seats/` (`assignments.csv`,
`audit-log.csv`). To use Google Sheets instead:

```bash
pip install office-cli[sheets]
export OFFICE_STORE=sheets
export OFFICE_SHEETS_ID=1abc...
export OFFICE_SHEETS_SA=/path/to/service-account.json
```

…or declare it in `data/offices.yaml`:

```yaml
storage:
  type: sheets
  sheets:
    spreadsheet_id: "1abc..."
    service_account: "data/sheets-service-account.json"
    cache_ttl_seconds: 300
```

Reads honor a 5-minute TTL cache; writes invalidate it. See
`docs/architecture.md` for the full storage contract.

### People directory (BambooHR)

`office` defaults to a no-op `StubDirectory` that trusts whatever email
it receives. Switch to BambooHR for the auto-vacate killer feature
(seats render as vacant automatically when an employee is offboarded):

```bash
pip install office-cli[bamboohr]
export OFFICE_DIRECTORY=bamboohr
export BAMBOOHR_SUBDOMAIN=tipalti
export BAMBOOHR_API_TOKEN=...   # env-only — do not commit
```

…or declare the public bits in `data/offices.yaml` and keep the token
in the env:

```yaml
directory:
  type: bamboohr
  bamboohr:
    subdomain: tipalti
    cache_ttl_seconds: 300
```

The directory affects rendering only; assignments stay in the store
unchanged. Re-activating an employee in BambooHR restores their seat
without any write.

### Slack `/whereis`

Run a Slack `/whereis` slash command backed by the same `SeatService`:

```bash
pip install office-cli[slack]
export SLACK_BOT_TOKEN=xoxb-...
export SLACK_APP_TOKEN=xapp-...
office slack-serve
```

Required Slack app scopes:

- `commands` — to register `/whereis`.
- `users:read.email` — for `users.info` to return `profile.email`.
- `chat:write` — to post the ephemeral response.

Three invocation shapes:

- `/whereis` — looks up the caller's own seat.
- `/whereis @user` — Slack mention; resolves the user's email.
- `/whereis email@domain` — plain text fallback.

Responses are **ephemeral by default** — only the caller sees them.
`hidden=TRUE` seats render as "occupied (private)" until role gating
(Stage 7) lifts the filter for privileged callers. Setting
`OFFICE_WEB_BASE_URL` adds an "Open map" deep-link button to the
response (placeholder until the web map ships in Stage 5).

## Adding a new floor

1. **Trace the floor in Inkscape** following `docs/tracing-guide.md` and
   the SVG ID contract in `CLAUDE.md`. Save as Plain SVG.
2. **Drop the SVG into `floors/`** as `<office>-floor-<N>.svg`.
3. **Add an entry to `data/offices.yaml`** with cluster capacities and
   any named rooms.
4. Verify: `office floors validate floors/<file>.svg`. Errors fail the
   command; warnings (e.g. cluster-capacity mismatches) are
   informational.

## Develop

```bash
uv sync
uv run pytest -n auto -v
uv run office --version
uv run python -m office_cli
```

## License

MIT — see `LICENSE`.
