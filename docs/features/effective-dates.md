# Effective-date windows

## What it is

Every assignment carries an `effective_from` and `effective_until`
date pair. The seat-listing surfaces (CLI, web, Slack) accept an
`as-of` parameter and render the seat map **as of that date**.
Future-dated assignments don't show until their window opens; past
assignments stop showing when their window closes.

## Why

HR and facilities teams plan ahead. Knowing "Alice moves to
5-T-04 on July 1" is real information; flipping the spreadsheet
on July 1 at 9 AM isn't. With effective dates, the operator
records the move now, and the system surfaces it automatically.
The web map's `?asOf=2026-07-15` query lets a planner ask "what
will the floor look like on the 15th?" without changing any data.

The contract intentionally avoids time-precision: dates only.
Day-granularity matches the UX, lex-sort comparison is correct on
ISO `YYYY-MM-DD`, and the storage shape stays plain text — no
per-backend timestamp gymnastics.

## Install

Built-in. No extra needed.

## Configure

No configuration. The feature is always on. CLI defaults to
**today** (the operator's wall-clock date) when `--as-of` is
omitted; web defaults to today (via the service's clock); Slack
defaults to today.

## Use

### CLI

```bash
office seats list --as-of 2026-07-15
office whereis alice@example.com --as-of 2026-07-15

# Schedule a future assignment:
office seats assign 5-T-01 alice@example.com --from 2026-07-01 --until 2026-12-31

# Defaults (no flags):
office whereis alice@example.com   # default = today
```

### Web

```text
http://localhost:8000/offices/tlv/floors/tlv-floor-5?asOf=2026-07-15
```

The frontend reads `asOf` from the URL, validates it
(`/^\d{4}-\d{2}-\d{2}$/` regex), and forwards it as
`/api/floors/<id>?as_of=2026-07-15`. The API accepts both
`as_of` (Python convention) and `asOf` (camelCase) for direct-API
callers.

### Slack

A trailing `YYYY-MM-DD` token on `/whereis`:

```text
/whereis alice@example.com 2026-07-15
/whereis @alice 2026-07-15
/whereis 2026-07-15                # self-lookup as-of a date
```

## How it works

### Storage shape

Both `effective_from` and `effective_until` are stored as
**date-only `YYYY-MM-DD` strings**. `last_updated` and audit-log
timestamps stay full ISO-8601 wall-clock — those record the *write
time*, not the *effective period*.

Date-only choice is intentional: the comparison is lex on ISO
strings (`"2026-07-15" < "2026-08-01"` is true), and an empty
string means open-ended (`""` < any real date, so it acts as
"begins always" for `from` and "never ends" for `until`).

### View-time filter

`SeatService.list_seats(as_of=...)` and
`SeatService.whereis(email, as_of=...)` apply
`is_effective(a, as_of_date)` to each row before returning:

```python
def is_effective(a, as_of_date):
    eff_from = _date_prefix(a.effective_from)   # strips T... if legacy
    eff_until = _date_prefix(a.effective_until)
    if eff_from and as_of_date < eff_from:
        return False
    if eff_until and as_of_date > eff_until:
        return False
    return True
```

Both bounds are **inclusive**. Pre-Stage-6 rows that wrote a full
ISO timestamp into `effective_from` keep working — the
`_date_prefix` helper strips `T...` before comparison.

### Order of view-time filters

Surfaces apply filters in this order:

1. **Date filter** (Stage 6) — out-of-window rows render vacant.
2. **Auto-vacate filter** (Stage 3) — inactive employees render
   vacant.
3. **Role redaction** (Stage 7) — viewer callers see hidden seats
   as `"(private)"`.

The order matters: a future-dated assignment to an offboarded
employee surfaces as vacant in both timeframes; the date filter
wins first.

### Validation

Every malformed date — CLI flag, URL param, Slack token —
surfaces as `OfficeError(EXIT_USER_ERROR)` with a contextual
remediation:

| Surface       | `parse_iso_date` `field=` / `example=`            |
| ------------- | ------------------------------------------------- |
| `--as-of`     | `field="--as-of"`, `example="--as-of 2026-07-01"` |
| `--from`      | `field="--from"`, `example="--from 2026-07-01"`   |
| `--until`     | `field="--until"`, `example="--until 2026-12-31"` |
| API `?as_of=` | `field="as_of"`, `example="?as_of=2026-07-01"`    |
| Slack token   | `field="as-of date"`, `example="2026-07-01"`      |

Calendar validation (`datetime.strptime`) rejects shapes the regex
accepts but the calendar doesn't (e.g. `2026-02-30`).

### Window validation

`validate_window(from_date, until_date)` runs in `SeatService.assign`
and rejects an inverted window with a clear message before any
write hits the store.

## Limits + roadmap

- **Date precision only.** No hour-granularity scheduling. Could
  land later, but the storage shape would have to change across
  all backends.
- **No multi-row scheduling per seat.** A future-dated assignment
  on a currently-occupied seat is rejected. Stage-9+ work could
  unlock multi-row scheduling (with `effective_until` driving the
  handoff), but isn't on the v1 roadmap.
- **No "what-if" mode.** Web shows the map at one date at a time;
  comparing two dates side-by-side is operator territory (open two
  tabs).
- **Audit-log timestamp stays wall-clock.** We never compare audit
  timestamps with `as_of`; that's the right contract.

## Related

- [CLI](./cli.md) — `--from` / `--until` / `--as-of` flags.
- [Web map](./web-map.md) — `?asOf=` URL semantics.
- [Slack `/whereis`](./slack.md) — trailing date token.
- [Architecture stages — Stage 6](../architecture.md) — PR-by-PR
  record.
