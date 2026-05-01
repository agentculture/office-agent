# Sheets ↔ Dynamo sync

## What it is

Two CLI verbs that make the [Sheets](./sheets.md) and
[DynamoDB](./dynamodb.md) backends interoperable rather than
exclusive:

- **`office seats migrate`** — one-shot import/export between any
  two backends (csv / sheets / dynamo).
- **`office seats sync`** — bi-directional reconciliation between
  Sheets and Dynamo with last-write-wins per row by `last_updated`.
  Idempotent — re-running converges.

## Why

Per the design constraint (and confirmed in
[CHANGELOG 0.8.0](../../CHANGELOG.md#080---2026-05-01)): **Sheets
stays a first-class runtime backend even with Dynamo on**.
Operators who prefer the spreadsheet UI as their human editor keep
using it; Dynamo gets the production read load. The two are kept in
agreement by `sync`. The `migrate` verb covers one-time moves
(bootstrap from Sheets, snapshot for offline review, etc.).

This is not a bidirectional replication daemon. It's a
reconciler operators run periodically (cron / GitHub Actions) and
that idempotently brings both sides into agreement.

## Install

Both backends:

```bash
pip install office-cli[sheets,dynamo]
```

## Configure

You need both backends configured at once — the verbs read source +
target in the same call. Either both via YAML, both via env, or one
of each. See [Sheets config](./sheets.md#configure) and
[Dynamo config](./dynamodb.md#configure).

## Use

### One-shot migrate

```bash
# Bootstrap Dynamo from Sheets:
office seats migrate --from sheets --to dynamo --dry-run   # preview
office seats migrate --from sheets --to dynamo

# Snapshot Dynamo back to Sheets for offline review:
office seats migrate --from dynamo --to sheets --audit-append

# CSV → anywhere:
office seats migrate --from csv --to dynamo
```

`--dry-run` prints a summary diff (rows new / overwritten /
unchanged + audit rows) without writing.

### Bi-directional sync

```bash
office seats sync --primary sheets --dry-run
office seats sync --primary sheets
```

`--primary` picks the **tie-breaker** when both sides have an
identical `last_updated` but the content diverged (rare; happens on
creation collisions or clock skew). It is **not** the source of
truth — the reconciler is symmetric. The flag only matters for the
tie case.

### Cron / GitHub Action cookbook

```yaml
# .github/workflows/seats-sync.yml
name: seats-sync
on:
  schedule: [{ cron: "*/15 * * * *" }]   # every 15 min
  workflow_dispatch: {}
jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv pip install -e '.[sheets,dynamo]'
      - run: office seats sync --primary sheets --json
        env:
          OFFICE_SHEETS_ID: ${{ secrets.OFFICE_SHEETS_ID }}
          OFFICE_SHEETS_SA: data/sheets-service-account.json
          OFFICE_DYNAMO_ASSIGNMENTS: office-assignments
          OFFICE_DYNAMO_AUDIT: office-audit-log
          OFFICE_DYNAMO_REGION: us-east-1
          AWS_ROLE_ARN: ${{ secrets.AWS_ROLE_ARN }}
```

`--json` makes the GitHub Action log machine-parseable so a
follow-up step can fail the run if `ties` is non-empty.

## How it works

### Module layout

| File                                  | Role                                   |
| ------------------------------------- | -------------------------------------- |
| `office_cli/cli/_commands/migrate.py` | `office seats migrate` verb.           |
| `office_cli/cli/_commands/sync.py`    | `office seats sync` verb.              |
| `office_cli/seats/_sync.py`           | Pure `reconcile()` reconciler. No I/O. |

### Migrate verb

Source and target are built from the same factory
(`build_backends_for_type(data_dir, store_type)`), which threads
the type override directly into `resolve_storage` — no environment
mutation.

The flow:

1. Read all assignments + audit entries from source.
2. Compute the diff against target (for the dry-run summary).
3. If the target is csv/sheets and its audit log is non-empty,
   bail out with a clear `OfficeError` unless the operator passed
   `--audit-append`. Sheets has no PK dedup, so a re-run would
   duplicate audit rows.
4. `target.upsert_many(assignments)` — idempotent by `seat_id`.
5. `target.audit.append_many(audit_entries)` — idempotent if
   target is Dynamo (PK + composite SK dedups), append-only
   otherwise.

### Sync verb

The reconciler in `_sync.py` is pure (no I/O). It takes left +
right snapshots and returns a `SyncPlan`:

```python
@dataclass(frozen=True)
class SyncPlan:
    write_left: list[Assignment]   # rows to push to the left side
    write_right: list[Assignment]  # rows to push to the right side
    audit_left: list[AuditEntry]   # audit rows to append left
    audit_right: list[AuditEntry]  # audit rows to append right
    ties: list[str]                # seat IDs that hit the tie-breaker
```

Per-row policy:

| Row state                                       | Action                                           |
| ----------------------------------------------- | ------------------------------------------------ |
| Only on left                                    | Copy to right.                                   |
| Only on right                                   | Copy to left.                                    |
| On both, identical content                      | No-op.                                           |
| On both, `last_updated` differs                 | Keep the side with the newer `last_updated`.     |
| On both, `last_updated` ties + content diverged | `ties.append(seat_id)`; tie-breaker = `primary`. |

Audit entries union into both sides, deduped by
`(seat_id, timestamp, action, employee_email)`. Dynamo's composite
SK dedups naturally on its side; the Sheets side does the in-memory
diff before append.

The `redacted` flag on `Assignment` is **excluded** from the
content equality check — it's a view-time flag from
[Stage 7](./roles.md), never persisted, so identical rows fetched
under different roles still compare equal.

### Idempotency

`reconcile()` is referentially transparent — same inputs, same
plan. After applying the plan, both sides agree, and a re-run
yields an empty plan. Test
`tests/test_seats_sync.py::test_idempotent_repeated_run` locks
this in.

### Mapping primary to left/right

The reconciler is named left/right (surface-neutral). The CLI
maps:

```python
primary="left"  if args.primary == "sheets" else "right"
```

Sheets is the left side by convention. Tie-breaker comments and
test fixtures use the same convention.

## Limits + roadmap

- **No always-on daemon** — `sync` is a one-shot reconciler.
  Operators run it via cron / GitHub Action. An always-on daemon
  could subscribe to DynamoDB Streams + Sheets webhook, but is
  Stage-9+.
- **No three-way merge** — content collisions on identical
  `last_updated` resolve via `--primary`. A real CRDT-shaped
  resolution would require an audit-log-driven causal history;
  out of scope.
- **No row-level dry-run diff** — `--dry-run` prints aggregated
  counts. A `--verbose` mode that lists the actual seat IDs
  would be a small ergonomic add.
- **`migrate --to sheets` audit append not idempotent** — Sheets
  has no PK dedup, so re-running on a non-empty audit tab would
  duplicate. Documented; the verb refuses unless
  `--audit-append` is passed.

## Related

- [Sheets backend](./sheets.md)
- [DynamoDB backend](./dynamodb.md)
- [Architecture stages — Stage 8](../architecture.md) — PR-by-PR
  record.
