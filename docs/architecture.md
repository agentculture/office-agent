# Architecture — v0.2.0 (Stage 1 + Stage 2)

`office` ships in stages on top of issue
[#1](https://github.com/agentculture/office-agent/issues/1). This document
captures **what is implemented today** and **what is deferred** so the
boundary stays explicit.

## Layered model

```text
   CLI verbs (office_cli.cli._commands)
            │
            ▼
   SeatService  ──►  AssignmentStore (Protocol)
   (office_cli.seats._service)        │
            │                         ├── CsvStore       ✓ implemented
            ▼                         ├── SheetsStore    ◌ deferred
   AuditLog (append-only CSV)         └── DynamoStore    ◌ deferred
            │
            ▼
   Office topology (office_cli.offices)
   ── load_offices(data_dir) → {Office → Floor → Cluster, Room}

   Floor SVG layer (office_cli.floors)
   ── parse_svg(path) → FloorSvg
   ── validate_floor(svg, floor) → list[Issue]
```

`office_cli.people` exposes an `EmployeeDirectory` Protocol with a
`StubDirectory` that trusts whatever email it receives. The
`BambooHRDirectory` lands in the BambooHR stage.

## Stage 1 — implemented in v0.1.0

- Frozen-dataclass domain models: `Office`, `Floor`, `Cluster`, `Room`,
  `Assignment`, `AuditEntry`, `Employee`.
- `data/offices.yaml` schema (`load_offices`).
- Floor SVG parser (`parse_svg`) — reads `<rect>` / `<polygon>` with `id`
  and `class`; ignores everything else.
- Validator (`validate_floor`) — view-box, ID format, cluster mapping,
  duplicate IDs, untagged-but-shaped IDs, capacity mismatch (warning).
- CSV-backed `AssignmentStore` (`CsvStore`) and append-only `AuditLog`.
- `SeatService` invariants: seat must exist; one seat per email
  globally; every mutation writes audit.
- CLI verbs: `office floors list|validate`, `office seats list|assign|
  unassign|move|history`, `office whereis EMAIL`. Every verb honors
  `--json` and the shared `--data-dir`.
- Sample data: `data/offices.yaml` (one office, one floor),
  `floors/tlv-floor-5.svg` (placeholder), `seats/*.example.csv`.
- Test fixtures + parametric tests on the ID contract, SVG parser,
  validator, store, service, and each CLI verb (text and JSON).

## Stage 2 — implemented in v0.2.0

- `office_cli.seats.sheets.SheetsStore` and `SheetsAuditLog` implement the
  same `AssignmentStore` / append-only audit contracts as the CSV pair.
- A thin `SheetsClient` Protocol (`read_rows`, `replace_rows`,
  `append_rows`) lives between the store and `gspread`, so unit tests
  use a `FakeSheetsClient` and never need real credentials.
- `GspreadClient` is the production adapter; gspread is imported lazily,
  so installations without the `[sheets]` extra still load
  `office_cli.seats` cleanly.
- 5-minute read cache (per-store, per-process); writes invalidate it.
- Storage selection (`office_cli._config.resolve_storage`):

  1. `storage:` block in `data/offices.yaml`,
  2. `OFFICE_STORE` / `OFFICE_SHEETS_ID` / `OFFICE_SHEETS_SA` env vars,
  3. CSV by default.

Install the extra to use Sheets:

```bash
pip install office-cli[sheets]
```

Configure either via `data/offices.yaml`:

```yaml
storage:
  type: sheets
  sheets:
    spreadsheet_id: "1abc..."
    service_account: "data/sheets-service-account.json"
    cache_ttl_seconds: 300
```

…or via env vars (which override the YAML block):

```bash
export OFFICE_STORE=sheets
export OFFICE_SHEETS_ID=1abc...
export OFFICE_SHEETS_SA=/abs/or/data-dir-relative/sa.json
```

The service-account JSON should be **git-ignored**.

## Deferred surfaces

Each is a separate issue/PR.

| Stage              | Surface                                       | Notes                                                                   |
| ------------------ | --------------------------------------------- | ----------------------------------------------------------------------- |
| 3. BambooHR        | `office_cli.people.BambooHRDirectory`         | Live pull, 5-min cache; auto-vacate on offboarding (the killer feature). |
| 4. Slack `/whereis`| `office_slack/` Bolt app                      | Imports `SeatService.whereis`; renders Block Kit with deep link.        |
| 5. Web frontend    | `office_web/` (Vite + a small Python server)  | Search-first map, `?asOf=YYYY-MM-DD`, role-aware `hidden` rendering.    |
| 6. Effective dates | service-layer `effective_from / _until`       | Columns already exist; the service starts honoring them.                |
| 7. SSO + roles     | viewer / editor / planning                    | Drives whether `hidden=TRUE` rows expose details.                       |
| 8. DynamoDB        | `office_cli.seats.DynamoStore`                | Migration script from Sheets, kept identical Protocol.                  |

## Operating notes

- Real assignment data lives in `seats/assignments.csv` and
  `seats/audit-log.csv`; both are git-ignored. Only the `*.example.csv`
  files are checked in as schema documentation.
- `OFFICE_DATA_DIR` (or `--data-dir DIR`) overrides where the CLI looks
  for `data/`, `floors/`, and `seats/`.
- The audit log is append-only by contract. "Who used to sit at X?" is
  literally the chronological projection of the audit-log CSV.
- `office_cli.seats.SeatService._build_seat_index` unions every loaded
  floor's seat IDs *and* every room declared in YAML, so rooms remain
  assignable even before someone traces them.
