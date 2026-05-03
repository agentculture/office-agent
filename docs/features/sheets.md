# Google Sheets backend

## What it is

A Google Sheets-backed `AssignmentStore` + `AuditLog` behind the
same Protocol the CSV and DynamoDB backends implement. Operators
who prefer the spreadsheet UI as their CMS can read and write
directly to a Sheet; the seat service reads through `gspread` and
caches results for 5 minutes.

## Why

Issue [#1](https://github.com/agentculture/office-agent/issues/1)
named Sheets the v1 source of truth. Two reasons:

- HR / facilities teams already use spreadsheets daily — no new UI
  to learn for the human editor.
- An audit trail in a separate tab is easy to read by a non-engineer.

When Stage 8 added DynamoDB, **Sheets stayed first-class**: the two
backends are interchangeable, and `office seats sync` keeps them in
agreement bi-directionally. See [Sheets ↔ Dynamo sync](./sync.md).

## Install

```bash
uv tool install 'office-cli[sheets]'
```

The package imports without `gspread`; only the `sheets` runtime
path lazy-imports it. CSV-only deployments don't pay for the
dependency tree.

## Configure

Three knobs: spreadsheet ID, service-account JSON, optional
cache-TTL seconds. YAML:

```yaml
storage:
  type: sheets
  sheets:
    spreadsheet_id: "1abc..."
    service_account: "data/sheets-service-account.json"
    cache_ttl_seconds: 300
```

…or env (overrides YAML, last-wins):

```bash
export OFFICE_STORE=sheets
export OFFICE_SHEETS_ID=1abc...
export OFFICE_SHEETS_SA=/path/to/service-account.json
```

The service-account JSON is **never** placed in YAML. The repo's
top-level `.gitignore` already protects `data/sheets-service-account.json`.

### Operator setup checklist

1. Create or pick a GCP project.
2. Enable the **Google Sheets API** for that project.
3. Create a service account; grant it no project-level IAM (only
   per-spreadsheet ACL is needed).
4. Generate a JSON key; save it as
   `data/sheets-service-account.json`.
5. Create a fresh spreadsheet, copy its ID from the URL.
6. **Share the spreadsheet** with the service-account email
   (`<sa>@<project>.iam.gserviceaccount.com`), role **Editor**.
7. Wire the YAML / env config above; run
   `office seats list` to verify.

## Use

```bash
office seats list                                      # reads from Sheets
office seats assign 5-T-01 alice@example.com           # writes a row
office seats history 5-T-01 --json                     # reads audit-log tab
office seats migrate --from sheets --to dynamo         # one-shot copy
office seats sync --primary sheets                     # bi-directional reconcile
```

## How it works

### Worksheet schema

The store expects two tabs: **`assignments`** and **`audit-log`**.
Both have a header row that matches the CSV column order exactly
(see `office_cli/seats/_csv_store.py:FIELDNAMES` and
`office_cli/seats/_audit.py:FIELDNAMES`).

`assignments` columns:

| Column            | Type   | Notes                                             |
| ----------------- | ------ | ------------------------------------------------- |
| `seat_id`         | string | `<floor>-<cluster>-<NN>` per the SVG ID contract. |
| `floor`           | string | Matches a floor id in `data/offices.yaml`.        |
| `employee_email`  | string | Empty for vacant seats.                           |
| `last_updated`    | string | ISO-8601 wall-clock timestamp.                    |
| `hidden`          | string | `TRUE` / `FALSE`.                                 |
| `notes`           | string | Free text.                                        |
| `effective_from`  | string | Date-only `YYYY-MM-DD` (Stage 6).                 |
| `effective_until` | string | Date-only `YYYY-MM-DD` or empty for open-ended.   |

`audit-log` columns: `timestamp, actor, action, seat_id,
employee_email, old_employee_email, note`. Rows are append-only.

### Read path

1. `SheetsStore.list()` checks the in-memory cache (default 5 min).
2. If stale: `gspread.Worksheet.get_all_values()` returns the whole
   tab as `list[list[str]]`.
3. Rows parse via `_rows_to_assignments` — empty / header-less rows
   skipped.
4. `by_email` filters in memory (no GSI). At v1 scale (~hundreds
   of seats) this is sub-millisecond.

### Write path

`SheetsStore.upsert_many` is a **whole-tab replace**:

1. Force-invalidate the cache (so we don't merge against a stale
   read window).
2. Re-read the tab (live state).
3. Merge incoming rows into the existing dict by `seat_id`.
4. Sort by `(floor, seat_id)`.
5. `clear()` + `update()` the whole worksheet in two requests.

The two-request shape is **not atomic** — a transport failure
between `clear` and `update` leaves the tab empty. The TTL cache
still holds the merged state in-process, so the next read populates
the tab from the cache via the same upsert path. Operators who
need stricter durability should snapshot the spreadsheet
periodically (Sheets has built-in version history).

### Audit-log shape

`SheetsAuditLog.append_many` is true append:

- If the tab is empty, write the header + new rows.
- If the tab has rows, `append_rows` to the bottom.

Re-running `migrate` against a Sheets target without
`--audit-append` is **rejected** because Sheets has no primary-key
dedup. See [sync.md](./sync.md) for the policy.

### Cache TTL

The cache lives in `SheetsStore._cache` + `_cache_at`. Default 5
minutes. Reads within the window return a copy of the cached list;
reads after the window go back to gspread. Writes always
invalidate the cache before re-reading.

A second writer hitting the same spreadsheet from a different
process is **invisible to the first process for up to TTL seconds**.
This is acceptable for the v1 use case (one CLI operator, one
daemon) but operators running the daemon + the spreadsheet UI in
parallel should know about it.

### Error mapping

| `gspread` error                         | `OfficeError` code             | Remediation surfaced                                       |
| --------------------------------------- | ------------------------------ | ---------------------------------------------------------- |
| Missing service-account file            | `EXIT_ENV_ERROR`               | "point OFFICE_SHEETS_SA at a real file"                    |
| `gspread` import not available          | `EXIT_ENV_ERROR`               | "install the sheets extra: uv tool install 'office-cli[sheets]'" |
| API permission denied (sa not shared)   | `EXIT_ENV_ERROR` (via gspread) | gspread message — the operator usually forgot to share.    |
| Bad YAML shape (`storage.sheets: nope`) | `EXIT_USER_ERROR`              | "must be a mapping in offices.yaml"                        |

Permission errors specifically should land cleanly as
`OfficeError`; if you see a raw gspread traceback, file a bug.

## Limits + roadmap

- **Whole-tab replace on writes** — fine at v1 scale; if rows grow
  past ~10k a row-level `update` would beat the clear+update
  pattern.
- **No GSI / index on email** — `by_email` is a linear scan over
  the cached list. Sub-millisecond at v1 scale.
- **No conflict detection** — two processes writing in the same
  TTL window can clobber each other. Mitigated by the v1 deployment
  model (one writer at a time); sync/migrate verbs do explicit
  read-merge-write cycles.
- **Spreadsheet name not in config** — only the ID. If the operator
  renames the spreadsheet that's fine; if they swap the ID
  pointing at a fresh sheet, the old data is lost. (Sheets version
  history is the recovery story.)

## Related

- [Sheets ↔ Dynamo sync](./sync.md) — keep the spreadsheet UI in
  agreement with the Dynamo runtime.
- [DynamoDB backend](./dynamodb.md) — the v2 production store; same
  Protocol, different operational characteristics.
- [Architecture stages — Stage 2](../architecture.md) — the
  PR-by-PR record of how Sheets landed.
