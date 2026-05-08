# Floor runbook — PDF to rendered map, end-to-end

The operator-facing checklist for adding a new floor. Each step is one
shell block; deeper docs are linked at the bottom.

This is the recipe surfaced by issue
[#54](https://github.com/agentculture/office-agent/issues/54): the
floor-5 walkthrough validated each piece individually, but operators
without an agent at their side need a single page that walks them
through the loop.

## Prerequisites

```bash
# Install poppler so process-pdf can render PNGs.
brew install poppler              # macOS
# or: apt install poppler-utils   # Debian/Ubuntu

# Inkscape — get it from inkscape.org.

# `office` CLI in this repo.
uv sync
uv run office --version
```

You also need:

- The architect's PDF (multi-page is fine).
- A Google Drive folder set up per
  [`floors-from-drive.md`](./floors-from-drive.md) (one folder per
  office, name ends with `(<office-id>)`).
- The service account email shared on the office folder. Read the
  ACL gotcha at the top of `floors-from-drive.md` before uploading
  if your Workspace enforces external-share rules.

## 1 — Convert the PDF page to PNG

```bash
bash .claude/skills/process-pdf/scripts/pdf-to-png.sh \
    ~/Downloads/<plan>.pdf "Fifth Floor" /tmp/floor5.png
# or by 1-based page number:
bash .claude/skills/process-pdf/scripts/pdf-to-png.sh \
    ~/Downloads/<plan>.pdf 10 /tmp/floor5.png
```

The skill produces a 1920-wide PNG. If the PDF has many pages with
similar text, use the page number — label search errors on
ambiguous matches by design.

## 2 — Trace in Inkscape

```text
File → New (1920×1080)
File → Import → /tmp/floor5.png  → choose **Embed** (not Link)
Lock the background layer
Trace one seat: <rect class="seat" id="5-T-01">
Ctrl+D, drag, bump id (5-T-02, 5-T-03, …)
Save As → Plain SVG → floors/tlv-floor-5.svg
```

Full steps: [`tracing-guide.md`](./tracing-guide.md). Watch for
the format-confirm dialog — dismissing it silently aborts the save.

## 3 — Doctor (clean up Ctrl+D cascade)

```bash
office floors doctor floors/tlv-floor-5.svg --dry-run    # preview
office floors doctor floors/tlv-floor-5.svg              # apply
```

Drops off-page shapes, dedupes near-duplicates, renumbers per the
cluster spec in `data/offices.yaml`. Existing valid ids are
preserved. The verb is also available as `office floors doctor
<floor-id>` once the floor is declared in `offices.yaml`.

## 4 — Validate locally

```bash
office floors validate floors/tlv-floor-5.svg
# or by id, once declared in offices.yaml:
office floors validate tlv-floor-5
```

Should print `OK`. If you see ≥3 `seat-id-format` errors sharing a
prefix, the validator suggests `office floors doctor` — go back to
step 3.

## 5 — Upload to Drive

Drag the SVG into the Drive office folder. **Replace** the existing
file if there is one (Drive keeps version history). Make sure the
service account still sees the file — corp Workspaces can require
re-sharing per file.

## 6 — Refresh the hydrator cache

```bash
office floors refresh
```

Required when `OFFICE_DRIVE_TTL_SECONDS > 0` (the default 300s is
the typical "iteration footgun"). For active iteration, set
`OFFICE_DRIVE_TTL_SECONDS=0` for the session and skip refresh.

## 7 — Validate via Drive

```bash
export OFFICE_DRIVE_ROOT="<folder-id>"
office floors validate tlv-floor-5
```

This proves the file is reachable from Drive, not just on disk.

## 8 — Render in the browser

```bash
uv run office serve
# open http://localhost:8000/offices/tlv/floors/tlv-floor-5
```

Smoke-checks: SVG renders (no broken-namespace error), seats and
rooms are clickable, assignments match the Sheet.

## Troubleshooting jumps

| Symptom | Page |
| ------- | ---- |
| Browser refuses the SVG as "not a valid SVG document" | [CLAUDE.md → SonarCloud guidance](../CLAUDE.md) (do not remove `ET.register_namespace`) |
| Drive folder lists empty in hydrator output | [`floors-from-drive.md` → Workspace ACL gotcha](./floors-from-drive.md) |
| Validator dumps dozens of garbled seat ids | [`tracing-guide.md` → Common gotchas](./tracing-guide.md) and step 3 above |
| Stale SVG keeps loading after Drive upload | step 6 above (`office floors refresh`) |
| Inkscape Save dialog seems to do nothing | [`tracing-guide.md` → Saving](./tracing-guide.md) — accept the Plain-SVG confirmation |

## See also

- [`tracing-guide.md`](./tracing-guide.md) — Inkscape side, deep version.
- [`floors-from-drive.md`](./floors-from-drive.md) — Drive side, deep version.
- [`architecture.md`](./architecture.md) — v1 design background.
- [`.claude/skills/process-pdf/SKILL.md`](../.claude/skills/process-pdf/SKILL.md) — PDF→PNG details.
