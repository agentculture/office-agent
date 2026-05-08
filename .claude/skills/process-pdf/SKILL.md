---
name: process-pdf
description: >
  Convert one page of a PDF into a PNG sized for floor-map SVG
  backgrounds. Use when extracting a specific floor / page from a
  multi-page architectural plan, converting PDF to PNG for an SVG
  background, or the user says "convert pdf", "extract page",
  "pdf to png". Requires `poppler` (pdftoppm + pdftotext) on PATH;
  the skill never installs anything itself.
---

# process-pdf

Convert a single page of a PDF into a PNG sized for the floor-map
tracing flow. The agent's `office floors validate` contract requires
SVGs whose `viewBox` is `0 0 1920 1080`; this skill produces a
**1920-wide PNG** by default so the output drops straight into
Inkscape as the `background` layer.

## Why this exists

Inkscape's PDF-as-vector import produces unusable SVGs for tracing
(architect plans yield ~100k vector elements; Inkscape's Plain SVG
export then breaks the XML somewhere in the mountain). The supported
path is to convert the PDF page to a raster PNG, embed that as the
`background` layer in the SVG, and trace `<rect class="seat">` /
`<polygon class="room">` over it. This skill is the conversion step.

See `docs/tracing-guide.md` for the full tracing flow.

## Prerequisites

The skill calls out to `poppler`'s `pdftoppm` (extract + scale) and
`pdftotext` (label-based page lookup). It never installs them.

| Platform        | Install command                |
| --------------- | ------------------------------ |
| macOS (Homebrew)| `brew install poppler`         |
| Debian / Ubuntu | `apt install poppler-utils`    |
| Fedora          | `dnf install poppler-utils`    |

If either binary is missing the skill exits 2 with a hint that
matches the platform.

## Usage

```bash
bash .claude/skills/process-pdf/scripts/pdf-to-png.sh \
    <pdf> <page-or-label> [out-png] [--width N] [--dpi N]
```

Two ways to pick the page:

- **Page number** — pass a positive integer (1-based).
- **Text label** — pass any string; the skill scans the PDF with
  `pdftotext` and uses the page that contains it. Errors with a
  candidate listing if zero or more than one page matches, so
  selection is always unambiguous.

Defaults:

- `out-png` → `<basename-of-pdf>-page<N>.png` in the current
  directory.
- `--width` → `1920` (matches the floor SVG viewBox).
- `--dpi` → `150` (good enough for tracing without bloating
  the file).

## Examples

**Canonical floor-tracing case** — find the "Floor 5" page in a
multi-floor pack and write a 1920-wide PNG:

```bash
bash .claude/skills/process-pdf/scripts/pdf-to-png.sh \
    ~/Downloads/tipalti-floors.pdf "Floor 5" /tmp/floor5.png
# stdout: /tmp/floor5.png
```

**Direct page number** when you already know it:

```bash
bash .claude/skills/process-pdf/scripts/pdf-to-png.sh \
    ~/Downloads/tipalti-floors.pdf 7 /tmp/floor5.png
```

**Custom width** (e.g. for a higher-res render outside the
floor-tracing flow):

```bash
bash .claude/skills/process-pdf/scripts/pdf-to-png.sh \
    plans.pdf 3 cover.png --width 3840 --dpi 300
```

## Output

On success: prints the absolute path of the produced PNG to stdout
and exits 0. So callers can capture it:

```bash
out=$(bash .claude/skills/process-pdf/scripts/pdf-to-png.sh \
    ~/Downloads/tipalti-floors.pdf "Floor 5" /tmp/floor5.png)
file "$out"   # PNG image data
```

## Errors and exit codes

- `0` — success.
- `1` — usage error (bad flags, missing positional args).
- `2` — environment error (poppler missing, PDF not found, label
  matches zero or multiple pages, page number out of range).

Stderr always includes a `hint:` line with the next concrete
action.

## Out of scope

- PDF→SVG vector extraction (the failure mode that prompted this
  skill).
- Auto-install of poppler.
- ImageMagick / sips fallbacks. Poppler is the single supported
  toolchain.
- Multi-page batch extract.
- OCR.
