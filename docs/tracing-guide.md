# Tracing a floor in Inkscape

Issue [#15](https://github.com/agentculture/office-agent/issues/15).
This is the human side of the v1 floor-plan system: how to turn an
architect's PDF into an SVG the agent can read.

The integration boundary is small — the parser only looks at `<rect>`
and `<polygon>` elements with `id` and `class` attributes. Everything
else (background images, layer groups, styling) is ignored. So the
question this guide answers is: **how do you produce those few
attributes in Inkscape, with the right values, and confirm they
survive the save?**

## Document setup

| Setting          | Value                          | Why                                    |
| ---------------- | ------------------------------ | -------------------------------------- |
| Page size        | 1920 × 1080 px                 | Matches the parser's expected viewBox. |
| Background image | **Embedded** (not linked)      | Linked images break on any other machine. |
| Background layer | **Locked**                     | Stops you nudging it while tracing.    |
| File format      | **Plain SVG** (not Inkscape)   | ~10× smaller; strips Inkscape namespaces. |

Pick `File → Document Properties` to set the page; pick
`File → Import` and choose **Embed** (not Link) when adding the
architect's plan.

## The ID contract

Every shape the agent cares about has both an `id` and a `class`.

| Object                                    | Shape       | `class` | `id` format                | Example         |
| ----------------------------------------- | ----------- | ------- | -------------------------- | --------------- |
| Open-space desk                           | `<rect>`    | `seat`  | `<floor>-<CLUSTER>-<NN>`   | `5-T-01`        |
| Phone / zoom room used as a desk          | `<rect>`    | `seat`  | same as above              | `5-Z-04`        |
| Named room from the architect's legend    | `<polygon>` | `room`  | architect id verbatim      | `5.18`          |
| Cluster boundary (optional, decorative)   | `<polygon>` | —       | `cluster-<floor>-<letter>` | `cluster-5-T`   |

Hard rules:

- Cluster letter **uppercase**. Sequence **zero-padded to 2 digits**.
  `5-T-01`, never `5-T-1`.
- Floor number first; the agent splits on the last `-` to recover it.
- IDs unique **within the file**.
- **No person data anywhere in the SVG** — names, emails, photos all
  live in the assignment store. The SVG is the layout; the store is
  the assignments. Mixing them blocks BambooHR-driven auto-vacate
  (the v1 killer feature) from working.

The `data/offices.yaml` topology declares each cluster's capacity per
floor. The validator warns if the seat-id count in the SVG doesn't
match.

## Setting `id` and `class` in Inkscape

Inkscape doesn't expose `class` in its main UI. Two reliable paths:

1. **XML editor** — `Ctrl+Shift+X`. Select a shape, set the `id` and
   `class` attributes directly. Most reliable; works for everything.
2. **Object Properties** — `Ctrl+Shift+O`. Note: the "Label" field
   maps to `inkscape:label`, **not** `id`. Don't use it for IDs. You
   can set `id` here, but `class` still needs the XML editor.

Workflow that scales:

1. Trace the first desk in a cluster. Set `id="5-T-01"` and
   `class="seat"` via the XML editor.
2. **Duplicate** with `Ctrl+D`, drag the copy into position, then
   bump the id (`5-T-02`, `5-T-03`, …). Inkscape preserves `class`
   on duplication, so you only edit `id` per copy.
3. After the cluster is done, run the validator (below) before
   moving on. Catching a typo at cluster N is much better than
   chasing it across the whole floor.

For rooms, the architect's legend usually labels them with the very
ids you want (`5.18`, `5.21`, …). Use those verbatim — don't
"clean them up" to a different scheme.

## Layer suggestion

The parser doesn't care about layers, but two layers make editing
easier and don't bloat the file:

```text
seats        ← all <rect class="seat"> elements
rooms        ← all <polygon class="room"> elements
background   ← the embedded architect plan, locked
```

You can hide `background` when reviewing IDs — the desks become
much easier to read.

## Saving

`File → Save As → Plain SVG`. **Not** Inkscape SVG. Plain SVG strips
Inkscape's `sodipodi:` and `inkscape:` namespaces, which the parser
ignores anyway, and keeps the file under ~50 KB.

Filename matches the floor id from `offices.yaml`:

| `offices.yaml` `floors[].id` | SVG filename       |
| ---------------------------- | ------------------ |
| `tlv-floor-5`                | `tlv-floor-5.svg`  |
| `fc-floor-2`                 | `fc-floor-2.svg`   |
| `nyc-floor-12`               | `nyc-floor-12.svg` |

## Validation loop

Run after every meaningful save:

```bash
uv run office floors validate floors/tlv-floor-5.svg
```

What it checks:

- Top-level `viewBox` is present and well-formed.
- Every `<rect>` / `<polygon>` with a seat-style id is tagged
  `class="seat"`; every room id is tagged `class="room"`. Untagged
  shapes are reported.
- Seat ids parse cleanly into `<floor>-<CLUSTER>-<NN>`.
- No duplicate ids.
- Cluster capacity in `offices.yaml` matches the seat count in the
  SVG (warning, not an error — useful while you're mid-trace).

Fix-and-rerun until clean. That's the dev loop.

## Common gotchas

| Symptom                                                                | Likely cause                                                                          |
| ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| `class` attribute disappeared after save                               | You saved as Inkscape SVG, not Plain SVG. Re-save with `Save As → Plain SVG`.         |
| Validator complains about extra ids                                    | A non-seat shape ended up with an id that matches the seat regex. Remove the id.      |
| Capacity warning persists                                              | Either add the missing seat in Inkscape, or update `clusters.<L>.capacity` in YAML.   |
| Background is fine on your laptop, broken everywhere else              | The image is linked, not embedded. Re-import with the **Embed** option.               |
| Architect's room id is `5/18` or `Room 18`                             | Use it **verbatim** — don't normalize. The store keys off the literal architect id.   |
| Two desks have the same id                                             | Probably a `Ctrl+D` you forgot to renumber. The validator points at both.             |

## End-to-end checklist

1. [ ] Page is 1920×1080, background embedded and locked.
2. [ ] Every desk: `<rect>`, `class="seat"`, id like `5-T-01`.
3. [ ] Every room: `<polygon>`, `class="room"`, architect id verbatim.
4. [ ] No person data anywhere in the file.
5. [ ] Saved as Plain SVG with the matching filename.
6. [ ] `uv run office floors validate` returns clean.
7. [ ] `data/offices.yaml` declares the floor and the right cluster
   capacities; the topology entry matches the SVG.
8. [ ] (Drive mode) The SVG is in the matching office folder in Drive
   — see [`floors-from-drive.md`](./floors-from-drive.md).

## Where the file lives

Two options, both supported:

- **Drive mode (recommended for non-engineer authors)**: drop the SVG
  into the Drive folder for the matching office. The agent picks it
  up live within the cache TTL. See
  [`floors-from-drive.md`](./floors-from-drive.md).
- **Local mode**: commit the file under `floors/<floor-id>.svg` and
  add the floor to `data/offices.yaml`. Useful for tests and dev.

## Next steps

- [`floors-from-drive.md`](./floors-from-drive.md) — how Drive-mode
  hydrates the YAML + SVGs from a shared folder.
- [`setup.md`](./setup.md) — getting the rest of `office` running.
- [`architecture.md`](./architecture.md) — the v1 design background.
