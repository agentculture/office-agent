"""HTTP routes for the seat-map server.

The endpoints are intentionally thin — they map ``SeatService`` /
``Office`` / ``Floor`` shapes to plain JSON, applying the **server-side
redaction** for ``hidden=TRUE`` rows so the frontend never sees a
private email or note.

Stage 7 will introduce role-based unredaction; until then every caller
is treated as a ``viewer``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from office_cli.cli._errors import EXIT_USER_ERROR, OfficeError
from office_cli.offices import Floor, Office
from office_cli.seats import Assignment, SeatService

_PRIVATE_PLACEHOLDER = "(private)"
_SHELL_PATH = Path(__file__).parent / "static" / "index.html"


def register_routes(app: Any, service: SeatService) -> None:
    from fastapi import HTTPException
    from fastapi.responses import HTMLResponse, RedirectResponse

    from office_cli.server._app import static_dir

    shell_html = _SHELL_PATH.read_text(encoding="utf-8")

    @app.get("/api/offices")
    def get_offices() -> dict:
        return {"offices": [_office_to_dict(office) for office in service.offices.values()]}

    @app.get("/api/floors/{floor_id}")
    def get_floor(floor_id: str) -> dict:
        floor, office_id = _resolve_floor(service, floor_id)
        if floor is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": f"unknown floor: {floor_id}",
                    "remediation": "GET /api/offices to see available floor ids",
                },
            )
        seats = [_redact(a) for a in service.list_seats(floor=floor_id)]
        return {
            "floor": _floor_to_dict(floor, office_id),
            "svg_url": f"/svgs/{floor.svg.name}",
            "seats": seats,
        }

    @app.get("/", response_class=RedirectResponse)
    def root() -> str:
        first = _first_floor_path(service)
        if first is None:
            return "/empty"
        return first

    @app.get("/empty", response_class=HTMLResponse)
    def empty_state() -> str:
        # The empty-state response just reuses the shell; the frontend
        # surfaces the no-floors banner from the API response shape.
        return shell_html

    @app.get("/floors/{floor_id}")
    def floor_redirect(floor_id: str, seat: str = "") -> RedirectResponse:
        """Resolve short ``/floors/{floor_id}`` URLs to the canonical SPA path.

        Slack's `/whereis` deep-link button (Stage 4) builds URLs of the
        form ``${OFFICE_WEB_BASE_URL}/floors/{floor}?seat={seat}`` — we
        redirect to ``/offices/{office}/floors/{floor}`` here so callers
        do not need to know the office id. ``seat`` is preserved
        verbatim; other query params are dropped since the documented
        v1 surface only carries ``seat``.
        """
        floor, office_id = _resolve_floor(service, floor_id)
        if floor is None:
            raise HTTPException(status_code=404, detail="unknown floor")
        target = f"/offices/{office_id}/floors/{floor_id}"
        if seat:
            target += f"?seat={seat}"
        return RedirectResponse(url=target, status_code=307)

    @app.get("/offices/{office_id}/floors/{floor_id}", response_class=HTMLResponse)
    def spa_shell(office_id: str, floor_id: str) -> str:
        # The shell is the same regardless of office/floor — the path
        # parameters are read by app.js from globalThis.location. We
        # still validate them server-side so an invalid URL surfaces
        # 404 rather than rendering a broken empty map.
        floor, declared_office = _resolve_floor(service, floor_id)
        if floor is None or declared_office != office_id:
            raise HTTPException(status_code=404, detail="unknown office or floor")
        return shell_html

    @app.exception_handler(OfficeError)
    async def office_error_handler(_request, err: OfficeError):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=400 if err.code == EXIT_USER_ERROR else 500,
            content={"error": err.message, "remediation": err.remediation},
        )

    # Stash so static_dir() callers (tests) can find it consistently.
    app.state.static_dir = static_dir()


def _office_to_dict(office: Office) -> dict[str, Any]:
    return {
        "id": office.id,
        "name": office.name,
        "address": office.address,
        "floors": [{"id": f.id, "status": f.status} for f in office.floors.values()],
    }


def _floor_to_dict(floor: Floor, office_id: str) -> dict[str, Any]:
    return {
        "id": floor.id,
        "office": office_id,
        "status": floor.status,
        "clusters": {
            k: {"capacity": c.capacity, "type": c.type} for k, c in floor.clusters.items()
        },
        "rooms": {
            k: {"name": r.name, "type": r.type, "capacity": r.capacity}
            for k, r in floor.rooms.items()
        },
    }


def _redact(a: Assignment) -> dict[str, Any]:
    """Server-side redaction for ``hidden=TRUE`` rows.

    The frontend never sees a private email or note. Notes are scrubbed
    whenever ``hidden=True`` regardless of whether ``employee_email`` is
    populated — a privately-flagged seat that happens to be vacant must
    not leak the operator's notes either. Stage 7 will pass a role
    argument that lifts this for editors / planning users.
    """
    if a.hidden:
        email_out: str | None = _PRIVATE_PLACEHOLDER if a.employee_email else None
        notes_out = ""
    else:
        email_out = a.employee_email or None
        notes_out = a.notes
    return {
        "seat_id": a.seat_id,
        "floor": a.floor,
        "employee_email": email_out,
        "last_updated": a.last_updated,
        "hidden": a.hidden,
        "notes": notes_out,
        "effective_from": a.effective_from or None,
        "effective_until": a.effective_until or None,
    }


def _resolve_floor(service: SeatService, floor_id: str) -> tuple[Floor | None, str]:
    for office in service.offices.values():
        if floor_id in office.floors:
            return office.floors[floor_id], office.id
    return None, ""


def _first_floor_path(service: SeatService) -> str | None:
    for office in service.offices.values():
        for floor in office.floors.values():
            return f"/offices/{office.id}/floors/{floor.id}"
    return None
