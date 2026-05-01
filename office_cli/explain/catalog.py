"""Markdown catalog for ``office explain <path>``.

Each entry is verbatim markdown. Keys are command-path tuples. The empty
tuple and ``("office",)`` both resolve to the root entry.

Keep bodies self-contained: an agent reading one entry should get enough
context without chaining reads.
"""

from __future__ import annotations

_ROOT = """\
# office

office is AgentCulture's CLI for seat assignments and meeting-room
operations across multiple office floors. From v0.1.0 the seating-system
data model and core CLI verbs are in place; Sheets / BambooHR / Slack /
web ship in subsequent stages on top of the same `office_cli.seats`
service layer.

## Verbs

- `office learn` — structured self-teaching prompt.
- `office explain <path>` — markdown docs for any noun/verb.
- `office whoami` — auth probe stub.
- `office floors list|validate` — list configured floors; validate SVGs.
- `office seats list|assign|unassign|move|history` — query and mutate
  seat assignments (CSV-backed in v0.1.0).
- `office whereis EMAIL` — find a person's seat (CLI mirror of Slack
  `/whereis`).

## Exit-code policy

- `0` success
- `1` user-input error
- `2` environment / setup error
- `3` internal error (unexpected exception)
- `4+` reserved

## See also

- `office explain learn`
- `office explain explain`
- `office explain whoami`
- `office explain floors`
- `office explain seats`
- `office explain whereis`
"""

_LEARN = """\
# office learn

Prints a structured self-teaching prompt covering office's purpose,
command map, exit-code policy, `--json` support, and `explain` pointer.

## Usage

    office learn
    office learn --json
"""

_EXPLAIN = """\
# office explain <path>

Prints markdown documentation for any noun/verb path. Unlike `--help`
(terse, positional), `explain` is global and addressable by path.

## Usage

    office explain office
    office explain learn
    office explain whoami
    office explain --json <path>
"""

_WHOAMI = """\
# office whoami

Probes authentication state across configured back-ends (BambooHR, Google
Sheets, Slack). In v0.0.1 this is a stub that always reports
`unauthenticated` — real auth wiring lands when the back-ends do.

## Usage

    office whoami
    office whoami --json

## Output

Text mode: a single status line (`unauthenticated`).

JSON mode: `{"status", "user", "backends": {...}}`. Field shapes are
stable; values evolve as back-ends come online.
"""


_FLOORS = """\
# office floors

List configured offices/floors and validate floor SVGs against the
`data/offices.yaml` topology.

## Subcommands

- `office floors list [--office ID] [--json] [--data-dir DIR]`
- `office floors validate [PATH] [--all] [--json] [--data-dir DIR]`

## Validation rules

A traced floor SVG must:

- have `viewBox="0 0 1920 1080"`;
- give every `<rect class="seat">` a `<floor>-<CLUSTER>-<NN>` id whose
  floor segment matches the floor entry's id;
- give every `<polygon class="room">` an architect id like `5.18`;
- have unique ids within the file.

Cluster capacities and room declarations missing from `offices.yaml`
surface as warnings (not failures).
"""

_FLOORS_LIST = """\
# office floors list

Walk `data/offices.yaml` and emit one row per declared floor: office id,
floor id, status, cluster summary, room count.

## Usage

    office floors list
    office floors list --office tlv
    office floors list --json

`--data-dir DIR` (or `OFFICE_DATA_DIR`) overrides the working directory.
"""

_FLOORS_VALIDATE = """\
# office floors validate

Validate one or all floor SVGs against the `data/offices.yaml` topology.
Errors fail the run with exit code 1; warnings do not.

## Usage

    office floors validate floors/tlv-floor-5.svg
    office floors validate --all
    office floors validate --all --json

## Output

Text: one line per floor (`OK` / `FAIL`) plus indented `error [rule]:` /
`warn [rule]:` lines. JSON: `{"results": [{"floor","ok","errors","warnings",...}]}`.
"""

_SEATS = """\
# office seats

List and mutate seat assignments stored under `seats/`. The CSV-backed
store in v0.1.0 is a stand-in for the Sheets-backed store coming next.

## Subcommands

- `office seats list [--floor F] [--cluster L] [--vacant|--occupied] [--json]`
- `office seats assign SEAT EMAIL [--note N] [--hidden] [--json]`
- `office seats unassign SEAT [--note N] [--json]`
- `office seats move EMAIL NEW_SEAT [--note N] [--json]`
- `office seats history SEAT [--json]`

## Invariants

- a seat must exist in some floor's SVG (or be a YAML-declared room);
- an employee holds at most one seat globally — re-assigning rejects
  with a hint to use `move`;
- every mutation appends an entry to `seats/audit-log.csv`.
"""

_SEATS_ASSIGN = """\
# office seats assign

Assign a seat to an employee email. Fails if the seat is occupied by a
different employee, or if the employee already holds another seat
globally (use `office seats move` instead).

## Usage

    office seats assign 5-T-01 alice@tipalti.com
    office seats assign 5.18 bob@tipalti.com --hidden --note "exec seat"

`--hidden` marks the row `hidden=TRUE`; non-privileged surfaces (web,
Slack) will render it as "occupied (private)".
"""

_SEATS_MOVE = """\
# office seats move

Atomically move an employee from their current seat to a new one. The
old seat is vacated and the new seat is assigned in a single operation;
two audit entries are written (one `unassign`, one `assign`) sharing a
timestamp.

## Usage

    office seats move alice@tipalti.com 5-T-02

Fails if the email has no current seat (use `assign`) or if the target
seat is occupied.
"""

_SEATS_HISTORY = """\
# office seats history

Return chronological audit-log entries for a seat. Answers "who used to
sit at 5-T-01?" without ever overwriting history — the audit log is
append-only.

## Usage

    office seats history 5-T-01
    office seats history 5-T-01 --json
"""

_WHEREIS = """\
# office whereis EMAIL

Find a person's current seat by email. The CLI mirror of the (planned)
Slack `/whereis` slash command — both surfaces call the same
`SeatService.whereis` underneath.

## Usage

    office whereis alice@tipalti.com
    office whereis alice@tipalti.com --json

Exits 0 even when no seat is found; the JSON payload reports
`assignment: null` so callers can disambiguate.
"""


ENTRIES: dict[tuple[str, ...], str] = {
    (): _ROOT,
    ("office",): _ROOT,
    ("learn",): _LEARN,
    ("explain",): _EXPLAIN,
    ("whoami",): _WHOAMI,
    ("floors",): _FLOORS,
    ("floors", "list"): _FLOORS_LIST,
    ("floors", "validate"): _FLOORS_VALIDATE,
    ("seats",): _SEATS,
    ("seats", "assign"): _SEATS_ASSIGN,
    ("seats", "move"): _SEATS_MOVE,
    ("seats", "history"): _SEATS_HISTORY,
    ("whereis",): _WHEREIS,
}
