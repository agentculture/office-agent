# DynamoDB backend

## What it is

A DynamoDB-backed `AssignmentStore` + `AuditLog` behind the same
Protocol the CSV and Sheets backends implement. It's the v2
production-shaped store: managed, multi-region-ready, and designed
to run alongside Sheets — not replace it. See
[Sheets ↔ Dynamo sync](./sync.md) for the bi-directional
reconciliation pattern.

## Why

The Sheets backend is great for human editing but limits production
ergonomics: latency tied to gspread's HTTP path, no per-row IAM,
no streaming change feed. DynamoDB gives:

- Predictable single-digit-ms read latency.
- Per-table IAM; service-to-service AWS auth.
- DynamoDB Streams (future hookup for webhooks / search indexing).
- Schema flexibility — adding a new attribute is a no-op write.

Issue [#1](https://github.com/agentculture/office-agent/issues/1)
named Dynamo as the v2 source of truth from the start, with the
schema explicitly **flat enough that a Sheets→Dynamo migration is
a copy operation**. That constraint shaped the choice of keys.

## Install

```bash
uv tool install 'office-cli[dynamo]'
```

The package imports without `boto3`; only the `dynamo` runtime
path lazy-imports it.

## Configure

YAML:

```yaml
storage:
  type: dynamo
  dynamo:
    table_assignments: office-assignments
    table_audit: office-audit-log
    region: us-east-1
    cache_ttl_seconds: 300
```

…or env (overrides YAML):

```bash
export OFFICE_STORE=dynamo
export OFFICE_DYNAMO_ASSIGNMENTS=office-assignments
export OFFICE_DYNAMO_AUDIT=office-audit-log
export OFFICE_DYNAMO_REGION=us-east-1
```

AWS credentials follow the standard chain (`AWS_PROFILE`, IAM
role, env vars). **Never** in YAML.

### Tables to provision

| Table                | Partition key (PK) | Sort key (SK)                                     | Notes                                             |
| -------------------- | ------------------ | ------------------------------------------------- | ------------------------------------------------- |
| `office-assignments` | `seat_id` (S)      | _none_                                            | One row per seat. Flat schema mirrors CSV cols.   |
| `office-audit-log`   | `seat_id` (S)      | `event_id` (S) — `"{timestamp}#{action}#{email}"` | Composite SK so same-second events don't collide. |

Use on-demand billing for both. Provisioned mode is fine too — at
v1 scale (hundreds of seats) the throughput is dominated by the
audit-log writes during sync runs.

### IAM

Minimum policy for the office-cli identity:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan",
        "dynamodb:PutItem", "dynamodb:BatchWriteItem"
      ],
      "Resource": [
        "arn:aws:dynamodb:us-east-1:*:table/office-assignments",
        "arn:aws:dynamodb:us-east-1:*:table/office-audit-log"
      ]
    }
  ]
}
```

## Use

```bash
office seats list                             # reads from Dynamo
office seats assign 5-T-01 alice@example.com  # writes via batch_writer
office seats history 5-T-01 --json            # query_by_pk on audit table

office seats migrate --from sheets --to dynamo  # bootstrap
office seats sync --primary sheets              # ongoing reconcile
```

## How it works

### Module layout

| File                                  | Role                                                 |
| ------------------------------------- | ---------------------------------------------------- |
| `office_cli/seats/dynamo/__init__.py` | Re-exports + lazy guards.                            |
| `office_cli/seats/dynamo/_client.py`  | `DynamoClient` Protocol + `Boto3DynamoClient` shim.  |
| `office_cli/seats/dynamo/_store.py`   | `DynamoStore` with TTL cache + in-memory `by_email`. |
| `office_cli/seats/dynamo/_audit.py`   | `DynamoAuditLog` with composite event_id SK.         |

### Read path

`DynamoStore.list()` mirrors the Sheets pattern:

1. Cache check (5-min TTL by default).
2. On miss: `scan` the table (paginated under the hood —
   `Boto3DynamoClient.scan_all` follows `LastEvaluatedKey`).
3. Build `Assignment` objects; cache; return a copy.

`by_email` is an in-memory linear scan over the cached list. At
v1 scale this is sub-millisecond; a future Stage-9 work item could
add a GSI on `employee_email` for direct query.

### Write path

`DynamoStore.upsert_many` uses `batch_put` (boto3's
`Table.batch_writer`) and invalidates the cache afterwards. PK
dedup means re-running the same upsert is a no-op for unchanged
rows.

### Audit-table SK rationale

The audit log keys on `(seat_id, event_id)` where:

```python
event_id = f"{timestamp}#{action}#{employee_email}"
```

Three reasons for this composite shape:

1. **Same-second collisions don't lose history.** `SeatService`
   produces second-precision timestamps. A rapid `assign →
   unassign` within the same wall-clock second would otherwise
   write to the same `(seat_id, timestamp)` key and the second
   `put_item` would overwrite the first, breaking the
   append-only contract.
2. **Lex order matches chronological order.** `#` sorts before any
   alphanumeric, so the timestamp prefix dominates the SK lex
   sort. `for_seat` queries return events in wall-clock order.
3. **Idempotent migrations.** Two re-runs of `migrate sheets
   dynamo` write the same SK, so `put_item` just overwrites the
   same row. No duplicate-row drift.

### Pagination

Both `scan_all` and `query_by_pk` walk `LastEvaluatedKey` until
DynamoDB returns no continuation. At v1 scale this is one round
trip; the loop is there so pagination doesn't surprise anyone if
the data set grows.

### Test harness

Tests use a hand-rolled `FakeDynamoClient` (in
`tests/test_dynamo_store.py`) — an in-memory dict keyed by `(pk,
sk)`. No `moto` dependency. The Protocol is the boundary, so the
fake matches the production shim's contract bit-for-bit.

## Limits + roadmap

- **No GSI on `employee_email`** — Stage-9 hardening. The 5-min
  cache + linear scan is fine for v1 scale; revisit when a
  deployment hits >5k seats.
- **No conditional writes** — `upsert_many` is unconditional.
  The migrate/sync verbs do explicit read-merge-write, so
  conflicts are visible at that layer; per-row CAS would be
  Stage-9+.
- **No DynamoDB Streams hookup** — a future webhook out to
  BambooHR / search index could subscribe to the stream; not on
  the roadmap.
- **One region per deployment** — multi-region replication is an
  AWS-level concern, not application.
- **Sheets stays first-class.** Dynamo doesn't replace Sheets;
  see [sync.md](./sync.md) for the bi-directional pattern.

## Related

- [Sheets backend](./sheets.md) — the v1 store, still supported.
- [Sheets ↔ Dynamo sync](./sync.md) — `migrate` and `sync` verbs.
- [Architecture stages — Stage 8](../architecture.md) — PR-by-PR
  record.
