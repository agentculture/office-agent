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
operations across multiple office floors. v0.0.1 ships only the agent-first
scaffold (`learn`, `explain`, `whoami`); real verbs (seat assign, room book,
where, etc.) land in later versions on top of the SVG-based floor plan
contract.

## Verbs

- `office learn` — structured self-teaching prompt.
- `office explain <path>` — markdown docs for any noun/verb.
- `office whoami` — auth probe stub.

## Exit-code policy

- `0` success
- `1` user-input error
- `2` environment / setup error
- `3+` reserved

## See also

- `office explain learn`
- `office explain explain`
- `office explain whoami`
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


ENTRIES: dict[tuple[str, ...], str] = {
    (): _ROOT,
    ("office",): _ROOT,
    ("learn",): _LEARN,
    ("explain",): _EXPLAIN,
    ("whoami",): _WHOAMI,
}
