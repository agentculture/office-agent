#!/usr/bin/env bash
# pdf-to-png — extract one page of a PDF as a 1920-wide PNG, sized
# for the floor-map tracing background. See ../SKILL.md.
#
# Usage:
#   pdf-to-png.sh <pdf> <page-or-label> [out-png] [--width N] [--dpi N]
#
# Exits:
#   0 success; out-png path printed to stdout
#   1 usage error
#   2 environment error (missing tool, missing pdf, ambiguous label, etc.)

set -euo pipefail

usage() {
    cat <<'EOF'
pdf-to-png — extract one page of a PDF as a PNG for floor-map tracing.

Usage:
  pdf-to-png.sh <pdf> <page-or-label> [out-png] [--width N] [--dpi N]

Arguments:
  <pdf>           Source PDF.
  <page-or-label> 1-based page number, OR a text label to search for.
                  Label mode requires the label to match exactly one page.
  [out-png]       Output path. Default: <pdf-basename>-page<N>.png in cwd.

Options:
  --width N       Output width in px (default 1920).
  --dpi N         Render DPI before scaling (default 150).
  --help          Show this message.

Requires poppler (pdftoppm + pdftotext) on PATH.
EOF
}

die() {
    local code=$1
    shift
    {
        echo "error: $*"
    } >&2
    exit "$code"
}

hint() {
    echo "hint: $*" >&2
}

# --- argparse ---------------------------------------------------------------

PDF=""
PAGE_OR_LABEL=""
OUT_PNG=""
WIDTH=1920
DPI=150

positional=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h) usage; exit 0 ;;
        --width)   WIDTH="${2:?--width needs a value}"; shift 2 ;;
        --dpi)     DPI="${2:?--dpi needs a value}"; shift 2 ;;
        --) shift; positional+=("$@"); break ;;
        --*) die 1 "unknown option: $1" ;;
        *) positional+=("$1"); shift ;;
    esac
done

if [[ ${#positional[@]} -lt 2 ]]; then
    usage >&2
    die 1 "missing required arguments"
fi

PDF="${positional[0]}"
PAGE_OR_LABEL="${positional[1]}"
OUT_PNG="${positional[2]:-}"

# --- prereq checks ----------------------------------------------------------

install_hint() {
    case "$(uname)" in
        Darwin) hint "install poppler: brew install poppler" ;;
        Linux)  hint "install poppler: apt install poppler-utils (Debian/Ubuntu) or dnf install poppler-utils (Fedora)" ;;
        *)      hint "install poppler from your platform's package manager" ;;
    esac
}

if ! command -v pdftoppm >/dev/null 2>&1; then
    install_hint
    die 2 "pdftoppm not found on PATH"
fi
if ! command -v pdftotext >/dev/null 2>&1; then
    install_hint
    die 2 "pdftotext not found on PATH"
fi

if [[ ! -f "$PDF" ]]; then
    hint "check the path; '~' is expanded by the shell so quote carefully"
    die 2 "PDF not found: $PDF"
fi

# --- resolve page number ---------------------------------------------------

PAGE=""
if [[ "$PAGE_OR_LABEL" =~ ^[0-9]+$ ]]; then
    PAGE="$PAGE_OR_LABEL"
else
    # Label search. pdftotext emits each page separated by ^L (form feed,
    # \x0c). Walk the output, count form feeds, find pages that contain
    # the label (case-insensitive substring). Require exactly one match.
    label_lower="$(printf '%s' "$PAGE_OR_LABEL" | tr '[:upper:]' '[:lower:]')"

    # Capture pdftotext's output and exit code separately so a poppler
    # failure (encrypted PDF, corrupt structure, etc.) surfaces as a
    # clean env error rather than getting confused with "0 matches".
    pdftotext_err="$(mktemp)"
    trap 'rm -f "$pdftotext_err"' EXIT
    if ! text="$(pdftotext -layout "$PDF" - 2>"$pdftotext_err")"; then
        err_msg="$(cat "$pdftotext_err")"
        hint "the PDF may be encrypted, corrupt, or unreadable by poppler"
        [[ -n "$err_msg" ]] && hint "pdftotext said: $err_msg"
        die 2 "pdftotext failed reading $PDF"
    fi

    matches=()
    page_no=1
    page_buf=""
    while IFS= read -r line; do
        if [[ "$line" == $'\x0c'* ]]; then
            if [[ "$(printf '%s' "$page_buf" | tr '[:upper:]' '[:lower:]')" == *"$label_lower"* ]]; then
                matches+=("$page_no")
            fi
            page_no=$((page_no + 1))
            page_buf="${line#$'\x0c'}"
        else
            page_buf+="$line"$'\n'
        fi
    done <<<"$text"
    # Tail page (no trailing form feed):
    if [[ "$(printf '%s' "$page_buf" | tr '[:upper:]' '[:lower:]')" == *"$label_lower"* ]]; then
        matches+=("$page_no")
    fi
    case "${#matches[@]}" in
        0) hint "no page contains '$PAGE_OR_LABEL' — try a different label or use a 1-based page number"
           die 2 "label '$PAGE_OR_LABEL' matched 0 pages" ;;
        1) PAGE="${matches[0]}" ;;
        *) hint "label '$PAGE_OR_LABEL' matched pages: ${matches[*]} — narrow the label or use a page number"
           die 2 "label matched ${#matches[@]} pages, expected exactly 1" ;;
    esac
fi

# --- resolve output path ----------------------------------------------------

if [[ -z "$OUT_PNG" ]]; then
    base="$(basename "$PDF")"
    base="${base%.*}"
    OUT_PNG="${base}-page${PAGE}.png"
fi

# Make output dir absolute / accessible.
out_dir="$(dirname "$OUT_PNG")"
if [[ ! -d "$out_dir" ]]; then
    hint "create the directory first (mkdir -p '$out_dir') or pass an existing path"
    die 2 "output directory does not exist: $out_dir"
fi

# --- extract + scale -------------------------------------------------------

# pdftoppm writes <prefix>-<NN>.png with N zero-padded to the page-count
# width (so page 7 of a 21-page doc → "<prefix>-07.png"). Use a tmp
# prefix and rename with a glob so we don't have to predict the padding.
tmpdir="$(mktemp -d)"
# Extend the EXIT trap to also clean up the tmpdir without dropping the
# pdftotext_err cleanup set above (if label-search ran).
trap 'rm -rf "$tmpdir"; rm -f "${pdftotext_err:-}"' EXIT
prefix="$tmpdir/page"

# Capture pdftoppm's exit code and stderr separately so an out-of-range
# page or encrypted PDF surfaces as an env error with a clear hint
# rather than just the bare poppler diagnostic.
pdftoppm_err="$(mktemp)"
trap 'rm -rf "$tmpdir"; rm -f "${pdftotext_err:-}" "${pdftoppm_err:-}"' EXIT
if ! pdftoppm \
        -png \
        -f "$PAGE" -l "$PAGE" \
        -r "$DPI" \
        -scale-to-x "$WIDTH" \
        -scale-to-y -1 \
        "$PDF" "$prefix" 2>"$pdftoppm_err"; then
    err_msg="$(cat "$pdftoppm_err")"
    hint "page $PAGE may be out of range, or the PDF may be encrypted/corrupt"
    [[ -n "$err_msg" ]] && hint "pdftoppm said: $err_msg"
    die 2 "pdftoppm failed for page $PAGE of $PDF"
fi

# Glob for the produced file. There must be exactly one.
shopt -s nullglob
produced=( "$prefix"-*.png )
shopt -u nullglob
if [[ ${#produced[@]} -ne 1 ]]; then
    hint "this is unexpected — please report it with the PDF page count and the page number you passed"
    die 2 "pdftoppm wrote ${#produced[@]} files, expected 1 (page $PAGE)"
fi

mv "${produced[0]}" "$OUT_PNG"

# Resolve to an absolute path for stdout.
if [[ "$OUT_PNG" = /* ]]; then
    abs="$OUT_PNG"
else
    abs="$(cd "$(dirname "$OUT_PNG")" && pwd)/$(basename "$OUT_PNG")"
fi
printf '%s\n' "$abs"
