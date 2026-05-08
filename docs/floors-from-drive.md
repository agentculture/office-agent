# Floors + config from Google Drive

Issue [#44](https://github.com/agentculture/office-agent/issues/44).

By default, `office` reads `data/offices.yaml` and `floors/*.svg` from
the working directory. With one env var, it instead reads them live
from a Google Drive folder — Inkscape stays the SVG editor, Drive
becomes the CMS, and you stop committing layout edits to the repo.

This is the same pattern the Sheets backend uses for assignments:
non-engineers (facilities, office managers) edit the source-of-truth
in a tool they already have, and the agent picks up changes within a
short cache window.

## Drive layout

Use one folder per office, named so the folder name **ends with**
`(<office-id>)`:

```text
<Org Drive>/Office Maps/                ← OFFICE_DRIVE_ROOT
  offices.yaml                          ← topology config
  Tel Aviv (tlv)/                       ← matches office id "tlv"
    tlv-floor-5.svg
    tlv-floor-6.svg
  Frankfurt (fc)/
    fc-floor-2.svg
  New York (nyc)/
    nyc-floor-12.svg
```

Permissions follow the building: TLV facilities gets edit on
`Tel Aviv (tlv)/`, Frankfurt facilities on theirs, etc. Read-only
share with the service-account email at the root level.

> **Workspace ACL gotcha.** Some corporate Google Workspaces
> (Tipalti's included) **do not propagate** a folder share to files
> later uploaded into that folder by a different account. The
> service account ends up with access to the folder but not to the
> files inside it, and Drive's API returns an empty listing — not a
> permission error. If `office floors validate <id>` reports a known
> floor as missing and the hydrator emits `office folder ... lists
> empty, but offices.yaml declares N floor(s) under it`, this is
> almost always why. Two ways to fix it:
>
> - **Share-before-upload**: share the office folder with the SA
>   first, *then* drop SVGs into it. Inheritance applies at upload
>   time.
> - **Per-file share**: select all files inside the folder and share
>   them individually with the SA email.

## `offices.yaml` shape (Drive copy)

The Drive YAML uses **bare filenames** for SVGs — no folder prefix:

```yaml
offices:
  - id: tlv
    name: "Tel Aviv"
    floors:
      - id: tlv-floor-5
        svg: tlv-floor-5.svg            # filename inside the office folder
        clusters:
          T: { capacity: 6, type: open-space }
          Z: { capacity: 2, type: phone-room }
        rooms:
          "5.18": { name: "Meeting Room 8P", type: meeting, capacity: 8 }
```

The hydrator looks up each SVG by name inside the matching office
folder. No Drive file ids appear in YAML; renaming or moving files in
Drive doesn't break anything as long as filenames + folder-id parens
stay aligned.

## Bootstrap

```bash
export OFFICE_DRIVE_ROOT="<folder-id>"            # required — gates drive mode on
# Optional knobs:
export OFFICE_DRIVE_CREDENTIALS=path/to/sa.json   # default: data/sheets-service-account.json
export OFFICE_DRIVE_TTL_SECONDS=300               # default: 300 (set to 0 to force refetch)
export OFFICE_DRIVE_CACHE_DIR=~/.cache/office-cli/drive
```

`OFFICE_DRIVE_ROOT` is the folder id, not a URL. From a Drive URL like
`https://drive.google.com/drive/folders/1AbC...xyz`, take the last
segment.

The same service account that powers the Sheets backend works for
Drive — just grant it the `drive.readonly` scope and share the root
folder with its email. If you'd rather isolate credentials, set
`OFFICE_DRIVE_CREDENTIALS` to a separate SA JSON.

## Install

```bash
pip install office-cli[drive]
# or, with uv from the repo:
uv sync --all-extras
```

## How resolution works

When `OFFICE_DRIVE_ROOT` is set, `resolve_data_dir()` calls
`hydrate_data_dir()` instead of returning the cwd. Hydration:

1. Lists the root folder. Finds `offices.yaml` at the top.
2. Downloads it (skipping if a fresh copy is already cached).
3. Parses it to discover declared offices.
4. For each office, finds the matching subfolder by the
   `(<office-id>)` suffix in its name.
5. Lists that subfolder, downloads each declared SVG (skipping fresh
   cached copies).
6. Writes a rewritten `offices.yaml` into the cache where each `svg:`
   field is a `floors/<filename>` relative path — the existing
   on-disk YAML resolver handles it from there.

The cache mirrors the on-disk data-dir layout:

```text
~/.cache/office-cli/drive/<root-folder-id>/
  data/offices.yaml
  floors/tlv-floor-5.svg
  seats/                       ← empty; CSV fallback writes here if used
  .meta/fetched-at.json        ← TTL bookkeeping
```

Downstream code (`load_offices`, `parse_svg`, the web map, Slack
`/whereis`) sees a normal-looking data dir; nothing knows it came
from Drive.

## Resolution order

`resolve_data_dir()` picks in this order (first match wins):

1. `--data-dir <PATH>` CLI flag — explicit override; useful for tests
   and dev loops.
2. `OFFICE_DATA_DIR` env var — same effect as `--data-dir`.
3. `OFFICE_DRIVE_ROOT` env var — eager hydrate, return the cache path.
4. `Path.cwd()` — the historical default.

So setting `--data-dir` or `OFFICE_DATA_DIR` always disables drive
mode for that invocation, even with `OFFICE_DRIVE_ROOT` set.

## Cache + TTL

- Per-file timestamps in `.meta/fetched-at.json`. On hydrate: if the
  cached file exists **and** age < TTL, the download is skipped.
- Default TTL: 300s (matches BambooHR + Sheets).
- `OFFICE_DRIVE_TTL_SECONDS=0` forces a fresh fetch every boot
  (useful for ops debugging, or right after an operator edits Drive).
- Cache invalidation: use the built-in verb (or delete the cache dir
  by hand if `office` isn't on PATH).

  ```bash
  office floors refresh                  # busts the hydrator cache
  rm -rf ~/.cache/office-cli/drive       # equivalent
  ```

### Iteration workflow

When iterating on a floor (Inkscape edit → Drive re-upload → render
check), TTL > 0 will keep serving the previous version for up to
five minutes. Two clean ways to skip the wait:

```bash
# Option A: short-circuit the cache for the iteration session.
export OFFICE_DRIVE_TTL_SECONDS=0
uv run office floors validate tlv-floor-5     # always fetches fresh

# Option B: keep TTL > 0, refresh between uploads.
unset OFFICE_DRIVE_TTL_SECONDS                # (or set to 300)
office floors refresh                         # after each Drive upload
uv run office floors validate tlv-floor-5
```

## End-to-end smoke test

```bash
export OFFICE_DRIVE_ROOT="<folder-id>"
rm -rf ~/.cache/office-cli/drive
uv run office floors validate tlv-floor-5
uv run office seats list
uv run office whereis ori.nachum@tipalti.com
```

Cold run hits Drive once for `offices.yaml` plus once per SVG. Warm
run within TTL makes zero Drive calls.

## Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| `offices.yaml not found at the root of OFFICE_DRIVE_ROOT` | Wrong folder id, or the SA isn't shared on the root folder. |
| `no Drive folder matches office id 'tlv'` | The office folder name doesn't end with `(tlv)`. Rename to `Tel Aviv (tlv)`. |
| `multiple Drive folders match office id 'tlv'` | Two folders both end with `(tlv)`. Remove or rename one. |
| `floor 'tlv-floor-5': SVG 'tlv-floor-5.svg' not found in office folder 'Tel Aviv (tlv)'` | The SVG isn't in that folder. The error lists what's actually there. |
| `google-api-python-client is not installed` | Run `pip install office-cli[drive]` (or `uv sync --all-extras`). |
| Stale data after editing in Drive | TTL hasn't expired; rerun with `OFFICE_DRIVE_TTL_SECONDS=0` once or `rm -rf ~/.cache/office-cli/drive`. |

## Out of scope

- Writing SVGs back to Drive — Inkscape stays the editor.
- Push notifications / webhook-driven cache invalidation — TTL is
  enough for v1.
- Roles via Google Groups / Active Directory — tracked in
  [#45](https://github.com/agentculture/office-agent/issues/45).
- Per-office Drive folders for `seats/` (assignment + audit log) —
  those stay in Sheets/Dynamo, addressed by the `storage:` block.

## See also

- [`docs/tracing-guide.md`](./tracing-guide.md) — how to produce the SVG you'll drop into the Drive folder.
- [`data/offices.yaml.example`](../data/offices.yaml.example) — local-fallback shape, used when `OFFICE_DRIVE_ROOT` is unset.
- [`docs/architecture.md`](./architecture.md) — full v1 design.
- [`docs/setup.md`](./setup.md) — getting started without Drive.
