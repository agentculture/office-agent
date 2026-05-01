"""Build the FastAPI app for ``office serve``.

The app has four concerns:

* the JSON API (``/api/offices``, ``/api/floors/{id}``);
* serving the floor SVGs as static files;
* serving the SPA shell + the bundled static assets at ``/static``;
* (Stage 7) optional SSO + role-aware redaction.

``fastapi`` is imported lazily so the parent package can be loaded
without the ``[web]`` extra installed (matches the pattern used by
:mod:`office_cli.seats.sheets`, :mod:`office_cli.people.bamboohr`, and
:mod:`office_cli.slack`). ``authlib`` and ``itsdangerous`` (the
``[sso]`` extra) are imported lazily inside :mod:`office_cli.server._auth`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from office_cli._roles import RolesConfig
from office_cli.cli._errors import EXIT_ENV_ERROR, OfficeError
from office_cli.seats import SeatService
from office_cli.server._auth import (
    OIDCConfig,
    install_session_middleware,
    register_auth_routes,
)
from office_cli.server._routes import register_routes

_STATIC_DIR = Path(__file__).parent / "static"


def build_app(
    service: SeatService,
    *,
    data_dir: Path | None = None,
    oidc: OIDCConfig | None = None,
    roles: RolesConfig | None = None,
) -> Any:
    """Construct the FastAPI app for ``service``.

    ``data_dir`` is used to resolve the ``floors/`` directory served as
    static SVG content. When omitted, the location is inferred from the
    first floor's ``svg`` path.

    ``oidc`` enables the SSO flow when set. ``None`` keeps auth
    disabled (dev / tests). ``roles`` is the role-mapping config; when
    ``None`` everyone is treated as ``viewer``.
    """
    try:
        from fastapi import FastAPI
        from fastapi.staticfiles import StaticFiles
    except ImportError as err:
        raise OfficeError(
            code=EXIT_ENV_ERROR,
            message="fastapi is not installed",
            remediation="install the web extra: pip install office-cli[web]",
        ) from err

    floors_dir = _floors_dir(service, data_dir)
    app = FastAPI(title="office", docs_url=None, redoc_url=None)
    roles_cfg = roles or RolesConfig()
    if oidc is not None:
        install_session_middleware(app, oidc)
        register_auth_routes(app, oidc, roles_cfg)
    register_routes(app, service, oidc=oidc, roles=roles_cfg)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
    # Mount under ``/svgs`` (not ``/floors``) so the bare ``/floors/{id}``
    # route below — used as a redirect entry point for Slack deep links —
    # is unambiguous.
    app.mount("/svgs", StaticFiles(directory=str(floors_dir)), name="svgs")
    return app


def _floors_dir(service: SeatService, data_dir: Path | None) -> Path:
    if data_dir is not None:
        return data_dir / "floors"
    # Infer from the first floor's ``svg`` path. Every loaded floor's
    # parent should be the same directory in practice.
    for office in service.offices.values():
        for floor in office.floors.values():
            return floor.svg.parent
    raise OfficeError(
        code=EXIT_ENV_ERROR,
        message="no floors are configured",
        remediation="declare at least one floor in data/offices.yaml",
    )


def static_dir() -> Path:
    """Public accessor for the bundled static directory (used by tests)."""
    return _STATIC_DIR
