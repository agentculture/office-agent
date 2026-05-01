"""HTTP routes for the seat-map server.

The endpoints are intentionally thin — they map ``SeatService`` /
``Office`` / ``Floor`` shapes to plain JSON, applying the **server-side
redaction** for ``hidden=TRUE`` rows so the frontend never sees a
private email or note.

Stage 7 will introduce role-based unredaction; until then every caller
is treated as a ``viewer``.
"""

from pathlib import Path
from typing import Any

from office_cli._dates import parse_iso_date, today_iso_date
from office_cli._roles import RolesConfig
from office_cli.cli._errors import EXIT_USER_ERROR, OfficeError
from office_cli.offices import Floor, Office
from office_cli.seats import Assignment, SeatService
from office_cli.server._auth import OIDCConfig, current_user, role_from_user

_PRIVATE_PLACEHOLDER = "(private)"
_SHELL_PATH = Path(__file__).parent / "static" / "index.html"


def register_routes(
    app: Any,
    service: SeatService,
    *,
    oidc: OIDCConfig | None = None,
    roles: RolesConfig | None = None,
) -> None:
    from fastapi import HTTPException, Query, Request
    from fastapi.responses import HTMLResponse, RedirectResponse

    from office_cli.server._app import static_dir

    shell_html = _SHELL_PATH.read_text(encoding="utf-8")
    _ = roles  # Reserved for future surface-side role config; service applies redaction.

    @app.get("/api/offices")
    def get_offices() -> dict:
        return {"offices": [_office_to_dict(office) for office in service.offices.values()]}

    @app.get("/api/floors/{floor_id}")
    def get_floor(
        request: Request,
        floor_id: str,
        as_of: str = "",
        # Accept ``?asOf=`` (camelCase) as an alias so direct-API callers
        # using the SPA URL convention work without translation. When both
        # are passed, ``as_of`` wins.
        as_of_camel: str = Query("", alias="asOf"),
    ) -> dict:
        user = current_user(request, oidc=oidc)
        return _build_floor_response(service, floor_id, as_of or as_of_camel, HTTPException, user)

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
    def spa_shell(request: Request, office_id: str, floor_id: str):
        # The shell is the same regardless of office/floor — the path
        # parameters are read by app.js from globalThis.location. We
        # still validate them server-side so an invalid URL surfaces
        # 404 rather than rendering a broken empty map.
        floor, declared_office = _resolve_floor(service, floor_id)
        if floor is None or declared_office != office_id:
            raise HTTPException(status_code=404, detail="unknown office or floor")
        # Stage 7: redirect anonymous browsers to SSO when auth is on.
        if oidc is not None and current_user(request, oidc=oidc) is None:
            next_url = request.url.path
            if request.url.query:
                next_url += f"?{request.url.query}"
            return RedirectResponse(url=f"/auth/login?next={next_url}", status_code=302)
        return HTMLResponse(content=shell_html)

    @app.exception_handler(OfficeError)
    async def office_error_handler(_request, err: OfficeError):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=400 if err.code == EXIT_USER_ERROR else 500,
            content={"error": err.message, "remediation": err.remediation},
        )

    # Stash so static_dir() callers (tests) can find it consistently.
    app.state.static_dir = static_dir()


def _build_floor_response(
    service: SeatService,
    floor_id: str,
    raw_as_of: str,
    http_exception: Any,
    user: dict[str, str] | None,
) -> dict[str, Any]:
    """Pure builder for the ``/api/floors/{id}`` JSON body.

    Lifted out of the closure inside :func:`register_routes` so the
    closure stays small (and the analyzer's cognitive-complexity ceiling
    stays satisfied as more routes accumulate).
    """
    floor, office_id = _resolve_floor(service, floor_id)
    if floor is None:
        raise http_exception(
            status_code=404,
            detail={
                "error": f"unknown floor: {floor_id}",
                "remediation": "GET /api/offices to see available floor ids",
            },
        )
    if raw_as_of:
        as_of_value: str | None = parse_iso_date(
            raw_as_of, field="as_of", example="?as_of=2026-07-01"
        )
        explicit = True
    else:
        as_of_value = today_iso_date(service._clock)
        explicit = False
    role = role_from_user(user)
    seats = [_redact(a) for a in service.list_seats(floor=floor_id, as_of=as_of_value, role=role)]
    return {
        "floor": _floor_to_dict(floor, office_id),
        "svg_url": f"/svgs/{floor.svg.name}",
        "seats": seats,
        # Echo the date back only when the caller asked for one — this is
        # what the frontend uses to decide whether to surface the banner.
        "as_of": as_of_value if explicit else None,
        "user": user,
    }


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
    """Stage 7 — surface mapping for an Assignment.

    Role-aware redaction is now done in :class:`SeatService` (it sets
    ``redacted=True`` for hidden rows when the caller's role is
    ``viewer``). This helper just maps that view-time state to the API
    JSON shape: redacted hidden rows render with the ``"(private)"``
    placeholder; everything else passes through.

    A non-redacted hidden row exists when the caller is editor/planning
    (full details) or when the row is hidden but vacant (Qodo Q4 from
    Stage 5 — notes are still scrubbed for all callers since the row's
    privacy intent stands).
    """
    if a.redacted:
        return {
            "seat_id": a.seat_id,
            "floor": a.floor,
            "employee_email": _PRIVATE_PLACEHOLDER,
            "last_updated": a.last_updated,
            "hidden": True,
            "notes": "",
            "effective_from": a.effective_from or None,
            "effective_until": a.effective_until or None,
        }
    if a.hidden:
        # Editor/planning view (or hidden-but-vacant seat). Email passes
        # through; notes still scrubbed when there's no occupant so a
        # privately-flagged empty seat doesn't leak the operator's notes.
        return {
            "seat_id": a.seat_id,
            "floor": a.floor,
            "employee_email": a.employee_email or None,
            "last_updated": a.last_updated,
            "hidden": True,
            "notes": a.notes if a.employee_email else "",
            "effective_from": a.effective_from or None,
            "effective_until": a.effective_until or None,
        }
    return {
        "seat_id": a.seat_id,
        "floor": a.floor,
        "employee_email": a.employee_email or None,
        "last_updated": a.last_updated,
        "hidden": False,
        "notes": a.notes,
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
