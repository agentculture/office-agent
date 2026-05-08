"""Generate a placeholder floor SVG from a PDF page.

A scaffold SVG embeds the chosen PDF page as a raster background, plus
one example ``<rect class="seat">`` and one example
``<polygon class="room">`` so the operator can immediately
``Ctrl+D``-duplicate them in Inkscape rather than starting from a
blank canvas. Issue #54.

The verb is PDF-agnostic: it takes any path + page selector and works
on any architectural plan whose page size is 1920×1080 (or close — the
PNG is rasterised at 1920 wide, preserving aspect).
"""

from __future__ import annotations

import base64
import io
import subprocess  # nosec B404 — we drive poppler with hard-coded argv
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET

from office_cli.cli._errors import EXIT_USER_ERROR, OfficeError
from office_cli.offices._models import Floor

_VIEW_W = 1920
_VIEW_H = 1080

# Match the doctor's namespace handling so scaffolds and doctored files
# both produce browser-compatible default-namespaced roots. CLAUDE.md
# documents this Sonar-S5332 caveat.
ET.register_namespace("", "http://www.w3.org/2000/svg")

_POPPLER_HINT = (
    "install poppler so pdftoppm/pdftotext are on PATH "
    "(macOS: brew install poppler; Debian/Ubuntu: apt install poppler-utils)"
)


def scaffold_svg(*, floor: Floor, pdf: Path, page: int | str) -> bytes:
    """Return SVG bytes for a placeholder floor backed by ``pdf`` page ``page``.

    ``page`` is either a 1-based integer or a text label (resolved via
    ``pdftotext`` against each page; ambiguous matches raise).

    The floor must declare at least one cluster — the scaffold needs a
    cluster letter to seed the example seat id. Floors without clusters
    raise ``OfficeError``.
    """
    if not floor.clusters:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=(
                f"floor {floor.id!r} declares no clusters; "
                "scaffold needs at least one to seed the example seat id"
            ),
            remediation=(
                "add a clusters block to the floor entry in offices.yaml "
                "(e.g. `clusters: { T: { capacity: 1, type: open-space } }`)"
            ),
        )
    page_num = _resolve_page(pdf, page)
    png = _render_pdf_page(pdf, page_num)
    return _build_svg(floor, png)


def _resolve_page(pdf: Path, page: int | str) -> int:
    """Return a 1-based page number for ``page``.

    Integer values pass through after a positivity check. String values
    are matched against the PDF's text content via ``pdftotext``; the
    function refuses ambiguous matches so selection is always unique.
    """
    if not pdf.is_file():
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"PDF not found: {pdf}",
            remediation="check the --pdf path",
        )
    if isinstance(page, int):
        if page < 1:
            raise OfficeError(
                code=EXIT_USER_ERROR,
                message=f"page must be 1-based; got {page}",
                remediation="pass --page <N> with N >= 1",
            )
        return page
    label = str(page).strip()
    if not label:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message="page label is empty",
            remediation="pass --page <N> or --page '<label-text>'",
        )
    pages = _pdf_page_count(pdf)
    matches: list[int] = []
    for i in range(1, pages + 1):
        text = _pdftotext_page(pdf, i)
        if label.lower() in text.lower():
            matches.append(i)
    if not matches:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"no page in {pdf.name} contains label {label!r}",
            remediation=(
                "pass --page <N> with a 1-based page number, or use a label "
                "string that appears verbatim on exactly one page"
            ),
        )
    if len(matches) > 1:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=(f"label {label!r} appears on multiple pages of {pdf.name}: " f"{matches}"),
            remediation="pass --page <N> with a specific page number to disambiguate",
        )
    return matches[0]


def _render_pdf_page(pdf: Path, page_num: int) -> bytes:
    """Run ``pdftoppm`` to render one page as a 1920-wide PNG.

    pdftoppm's ``-singlefile -`` form writes a literal ``-.png`` file
    rather than streaming to stdout, so we use a tempfile prefix and
    read the result back. The temp file is removed before returning.
    """
    with tempfile.TemporaryDirectory(prefix="office-scaffold-") as tmp:
        prefix = Path(tmp) / "out"
        cmd = [
            "pdftoppm",
            "-png",
            "-scale-to-x",
            str(_VIEW_W),
            "-scale-to-y",
            "-1",
            "-f",
            str(page_num),
            "-l",
            str(page_num),
            "-singlefile",
            str(pdf),
            str(prefix),
        ]
        _run_poppler(cmd, "pdftoppm")
        out_png = prefix.with_suffix(".png")
        if not out_png.is_file():
            raise OfficeError(
                code=EXIT_USER_ERROR,
                message=(f"pdftoppm produced no output for {pdf} page {page_num}"),
                remediation="check the page number is in range; try the page label form",
            )
        return out_png.read_bytes()


def _pdf_page_count(pdf: Path) -> int:
    """Return the page count via ``pdfinfo``."""
    out = _run_poppler(["pdfinfo", str(pdf)], "pdfinfo").decode("utf-8", errors="replace")
    for line in out.splitlines():
        if line.startswith("Pages:"):
            try:
                return int(line.split()[1])
            except (IndexError, ValueError):
                break
    raise OfficeError(
        code=EXIT_USER_ERROR,
        message=f"could not parse page count from pdfinfo output for {pdf}",
        remediation="check the PDF is well-formed; pdfinfo output had no Pages: line",
    )


def _pdftotext_page(pdf: Path, page_num: int) -> str:
    """Return the text of one page via ``pdftotext``."""
    cmd = [
        "pdftotext",
        "-layout",
        "-f",
        str(page_num),
        "-l",
        str(page_num),
        str(pdf),
        "-",
    ]
    return _run_poppler(cmd, "pdftotext").decode("utf-8", errors="replace")


def _run_poppler(cmd: list[str], binary: str) -> bytes:
    """Invoke a poppler binary, surfacing missing-binary + non-zero exit cleanly."""
    try:
        result = subprocess.run(  # nosec B603 — argv is hard-coded, no shell
            cmd,
            capture_output=True,
            check=True,
        )
    except FileNotFoundError as err:
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"{binary} not on PATH",
            remediation=_POPPLER_HINT,
        ) from err
    except subprocess.CalledProcessError as err:
        stderr = (err.stderr or b"").decode("utf-8", errors="replace").strip()
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"{binary} failed (exit {err.returncode}): {stderr or 'no stderr'}",
            remediation="check the PDF is well-formed and the page number is in range",
        ) from err
    return result.stdout


def _build_svg(floor: Floor, png_bytes: bytes) -> bytes:
    """Assemble the SVG: embedded PNG + one example seat + one example room."""
    root = ET.Element(
        "svg",
        {
            "xmlns": "http://www.w3.org/2000/svg",
            "viewBox": f"0 0 {_VIEW_W} {_VIEW_H}",
            "width": str(_VIEW_W),
            "height": str(_VIEW_H),
        },
    )
    encoded = base64.b64encode(png_bytes).decode("ascii")
    ET.SubElement(
        root,
        "image",
        {
            "x": "0",
            "y": "0",
            "width": str(_VIEW_W),
            "height": str(_VIEW_H),
            "href": f"data:image/png;base64,{encoded}",
        },
    )
    cluster_letter = sorted(floor.clusters.keys())[0]
    seat_id = f"{floor.number}-{cluster_letter}-01"
    ET.SubElement(
        root,
        "rect",
        {
            "id": seat_id,
            "class": "seat",
            "x": "100",
            "y": "100",
            "width": "51",
            "height": "25",
        },
    )
    if floor.rooms:
        room_id = next(iter(floor.rooms.keys()))
        ET.SubElement(
            root,
            "polygon",
            {
                "id": room_id,
                "class": "room",
                "points": "200,200 260,200 260,240 200,240",
            },
        )
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    buf = io.BytesIO()
    tree.write(buf, encoding="utf-8", xml_declaration=True)
    return buf.getvalue()
