# BambooHR + auto-vacate

> **Status: gated off by default.** The BambooHR backend is wired
> end-to-end but disabled at runtime. Even when `directory.type: bamboohr`
> is set in `offices.yaml` or `OFFICE_DIRECTORY=bamboohr` is exported,
> the seat service falls back to the `stub` directory and prints a
> one-line warning to stderr unless `OFFICE_BAMBOOHR_ENABLED=1` is set.
> All code, configuration plumbing, and tests below remain functional —
> opt in with the env flag to re-enable.

## What it is

A BambooHR-backed `EmployeeDirectory` that powers the system's
single most valuable feature: **a seat assigned to an offboarded
employee renders as vacant automatically — no Sheet edit, no
manual cleanup**. The directory is consulted at view time on
every `seats list` / `whereis` call.

## Why

Offboarding is one of the few HR events that absolutely must
propagate quickly. The historical pattern (Sheet-as-source-of-truth)
relied on a human remembering to delete a row when a person left;
in practice that step lagged or was skipped. The auto-vacate
contract removes the human entirely:

> When BambooHR no longer returns an employee in its
> `/v1/employees/directory` response, every seat assigned to them
> renders as vacant.

The assignment row in the store is **not** mutated. The filter is
applied at view time. If the employee is re-activated in BambooHR
(or BambooHR is unreachable — fail-open), their seat reappears. No
data is lost.

## Install

```bash
uv tool install 'office-cli[bamboohr]'
```

The package imports without `requests`; only the `bamboohr`
runtime path lazy-imports it.

## Configure

YAML:

```yaml
directory:
  type: bamboohr
  bamboohr:
    subdomain: tipalti
    cache_ttl_seconds: 300
```

…and set the API token as an env var (it's a secret — **never**
in YAML). You also need to flip the runtime gate:

```bash
export OFFICE_BAMBOOHR_ENABLED=1   # required: opt in to the gated feature
export BAMBOOHR_API_TOKEN=...
# Optional env overrides:
export OFFICE_DIRECTORY=bamboohr
export BAMBOOHR_SUBDOMAIN=tipalti
```

Without `OFFICE_BAMBOOHR_ENABLED=1`, the service silently uses the stub
directory and emits a single `warning: BambooHR backend is gated off …`
line to stderr.

`cache_ttl_seconds` is capped at 300 (5 minutes) so an offboard
event can't sit stale for more than that. The cap is enforced in
`office_cli/_config.py` — operators who try to set 1 hour get a
clear `OfficeError(EXIT_USER_ERROR)`.

## Use

The directory is read transparently — no new verb. Just run the
existing seat-lookup commands:

```bash
office seats list                      # rows for offboarded employees render vacant
office whereis bob@example.com         # returns None if Bob isn't in BambooHR
office whereis bob@example.com --json  # → {"email": "bob@example.com", "assignment": null}
```

Slack `/whereis` and the web map honor the same filter (they share
the `SeatService`).

## How it works

### Module layout

| File                                       | Role                                                 |
| ------------------------------------------ | ---------------------------------------------------- |
| `office_cli/people/__init__.py`            | `Employee` dataclass + `EmployeeDirectory` Protocol. |
| `office_cli/people/_stub.py`               | `StubDirectory` — default; trusts every email.       |
| `office_cli/people/bamboohr/_client.py`    | `RequestsBambooHRClient` (lazy `requests` shim).     |
| `office_cli/people/bamboohr/_directory.py` | `BambooHRDirectory` — TTL cache, fail-open.          |

### View-time filter

`SeatService._apply_autovacate(a)` runs in both `list_seats` and
`whereis`:

```python
def _apply_autovacate(self, a):
    if not a.employee_email:
        return a
    if self.directory.is_active(a.employee_email):
        return a
    # cleared email + hidden=False so the row renders as plain vacant
    return dataclasses.replace(a, employee_email="", hidden=False)
```

The store row stays unchanged. Only the in-memory `Assignment`
returned to the surface is mutated.

### TTL cache + fail-open semantics

`BambooHRDirectory` keeps a snapshot of active employees in memory
with a 5-minute TTL. The behavior on a refresh:

| Scenario                               | Action                                                                            |
| -------------------------------------- | --------------------------------------------------------------------------------- |
| Cache fresh (within TTL)               | Use cache; no API call.                                                           |
| Cache stale + API succeeds             | Replace cache; reset TTL.                                                         |
| Cache stale + API fails (network, 5xx) | **Fail-open**: keep the stale cache, emit a stderr warning with the cache age.    |
| Cache stale + API returns empty        | Replace with empty cache → all seats render vacant (this is the offboard signal). |

A separate `_last_attempt_at` tracks failed-refresh attempts so we
don't hammer BambooHR on every CLI call when the API is down.

Fail-open is intentional: a temporary BambooHR outage shouldn't
cause the whole seat map to look offboarded.

### Why we never store names locally

`Employee` carries `email` and a display `name` field. The
directory layer is the **only** place names live; we **never**
write them to the assignment store. Reasons:

- GDPR / data-minimization: the audit log only needs the email
  (which is already a join key); the human-readable name belongs
  to the source of truth.
- Stale-name avoidance: if Sarah Smith becomes Sarah Jones, the
  Sheet doesn't end up with two different names for the same seat
  — the rendering layer always asks the directory.

## Limits + roadmap

- **Token in env only** — by design. If your shell history is
  shared, use `direnv` or an OS keychain to scope the variable.
- **No webhook integration** — the auto-vacate latency is bounded
  by the cache TTL (default 5 min). A future Stage-9+ work item
  could subscribe to BambooHR's webhook for instant invalidation;
  not on the v1 roadmap because 5 minutes is fine for our use case.
- **No name redaction in audit log** — the audit log carries the
  email, never the name, but operators with access to the audit
  log can still join against BambooHR. Audit-log redaction is
  explicitly out of scope per [issue #11](https://github.com/agentculture/office-agent/issues/11).
- **`StubDirectory` is the default** — installations that don't
  set `OFFICE_DIRECTORY=bamboohr` get pass-through behavior (every
  email is "active"). This is right for local dev; production
  should set the env var.

## Related

- [Architecture stages — Stage 3](../architecture.md) — PR-by-PR
  record.
- [SSO + roles](./roles.md) — Slack `/whereis` resolves the
  caller's email via `users.info` and then looks up their role in
  the `RolesConfig` map (loaded from `data/offices.yaml`); BambooHR
  is consulted only for the queried subject's identity, not for the
  caller's role.
- [Effective-date windows](./effective-dates.md) — auto-vacate
  runs **after** the date filter, so a future-dated assignment to
  an offboarded employee surfaces as vacant in both timeframes.
