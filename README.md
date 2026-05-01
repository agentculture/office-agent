# office

Agent-first CLI for managing seat assignments and meeting rooms across
office floor plans. Floor layouts are hand-traced SVGs; people come from
BambooHR; assignments live in a Google Sheet (v1) or DynamoDB (v2). The
CLI exposes the same operations as the Slack `/whereis` command and the
web map.

> **Status — v0.0.1.** This release ships only the agent-first scaffold
> (`learn`, `explain`, `whoami`). Real verbs (seat assign, room book,
> where, …) land in later versions on top of the SVG floor-plan contract
> defined in [issue #1](https://github.com/agentculture/office-agent/issues/1).

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
office learn              # structured self-teaching prompt
office learn --json       # same, JSON-shaped
office explain office     # markdown root entry
office explain whoami     # docs for any verb
office whoami             # auth probe (returns "unauthenticated" in v0.0.1)
office whoami --json      # JSON: {status, user, backends}
```

## Develop

```bash
uv sync
uv run pytest -n auto -v
uv run office --version
uv run python -m office_cli
```

## License

MIT — see `LICENSE`.
