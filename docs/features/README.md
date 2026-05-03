# Feature deep-dives

Each page below documents one feature surface — what it is, why it
exists, how to install / configure it, how to use it, and how it
works under the hood.

**First-time setup?** Start with [`../setup.md`](../setup.md) for the
quick-start walkthrough and the optional-features index; the pages
below are deep dives, not entry points.

For the **stage-by-stage implementation history** (how each feature
got added across PRs), see [`docs/architecture.md`](../architecture.md).
For the **product-level overview**, see the
[top-level README](../../README.md).

## Index

| Feature                                        | Status  | One-liner                                                                                  |
| ---------------------------------------------- | ------- | ------------------------------------------------------------------------------------------ |
| [Agent-first CLI](./cli.md)                    | Shipped | `office` is the public surface — `learn` / `explain` make it self-documenting for agents.  |
| [Google Sheets backend](./sheets.md)           | Shipped | Spreadsheet-backed `AssignmentStore` with append-only audit log and a 5-minute read cache. |
| [BambooHR + auto-vacate](./bamboohr.md)        | Shipped | Live people directory; offboarding in BambooHR auto-vacates seats with **no Sheet edit**.  |
| [Slack `/whereis`](./slack.md)                 | Shipped | Socket-mode slash command that resolves `@user` / email / self-lookup to a seat ID.        |
| [DynamoDB backend](./dynamodb.md)              | Shipped | The third runtime store; same `AssignmentStore` Protocol as CSV / Sheets.                  |
| [Sheets ↔ Dynamo sync](./sync.md)              | Shipped | `office seats migrate` (one-shot) and `office seats sync` (last-write-wins, idempotent).   |
| [Search-first web map](./web-map.md)           | Shipped | Vanilla-JS SPA with deep-linkable URLs over a FastAPI seat-map server.                     |
| [Effective-date windows](./effective-dates.md) | Shipped | `--from` / `--until` / `--as-of` everywhere; date-only storage, lex-sort comparison.       |
| [SSO + roles](./roles.md)                      | Shipped | OIDC on the web; viewer / editor / planning gating; CLI stays unrestricted.                |

## Doc skeleton

Every feature page follows the same structure so you can skim
directly to what you need:

1. **What it is** — one paragraph.
2. **Why** — design rationale, what problem it solves.
3. **Install / configure** — pip extra, env vars, YAML keys.
4. **Use** — copy-pasteable commands.
5. **How it works** — internals at the level useful to operators
   and contributors.
6. **Limits + roadmap** — known constraints, deferred features.
7. **Related** — cross-links.
