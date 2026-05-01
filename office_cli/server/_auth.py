"""SSO + role resolution for the FastAPI seat-map server (Stage 7).

Three modes of operation:

* **Auth disabled** (``oidc=None``): no SessionMiddleware, no
  ``/auth/*`` routes, no redirects. ``current_user`` returns ``None``
  (or, when an ``X-Test-Role`` header is present, a synthetic test
  user with that role). This is the default for local dev and tests.
* **Auth enabled** (``oidc`` is an :class:`OIDCConfig`): a signed-cookie
  session middleware is mounted, ``/auth/login`` /
  ``/auth/callback`` / ``/auth/logout`` routes register, and
  ``require_user`` redirects unauthenticated requests to login.

The OIDC integration uses :mod:`authlib.integrations.starlette_client`,
imported lazily so the package loads cleanly without the ``[sso]``
extra installed (mirrors :mod:`office_cli.server._app` and
:mod:`office_cli.slack._app`).

The ``X-Test-Role`` header is honored **only when auth is disabled** —
once OIDC is configured, the session is the sole source of identity.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from office_cli._roles import VIEWER, RolesConfig, role_for_email
from office_cli.cli._errors import EXIT_ENV_ERROR, OfficeError

_OIDC_ENV_VARS = (
    "OIDC_ISSUER",
    "OIDC_CLIENT_ID",
    "OIDC_CLIENT_SECRET",
    "OIDC_REDIRECT_URL",
    "SESSION_SECRET",
)
_TEST_ROLE_HEADER = "x-test-role"
_SESSION_USER_KEY = "user"


@dataclass(frozen=True)
class OIDCConfig:
    """Resolved OIDC configuration. All five env vars are required."""

    issuer: str
    client_id: str
    client_secret: str
    redirect_url: str
    session_secret: str


def resolve_oidc(env: dict[str, str] | None = None) -> OIDCConfig | None:
    """Build an :class:`OIDCConfig` from env, or return ``None``.

    Returns ``None`` when **none** of the env vars are set (auth-disabled
    mode). Returns a populated config when **all five** are set. When
    only some are set, raises :class:`OfficeError(EXIT_ENV_ERROR)` so
    operators get a clear hint instead of a silently-disabled IdP.
    """
    e = env if env is not None else os.environ
    present = {name: e.get(name, "").strip() for name in _OIDC_ENV_VARS}
    set_count = sum(1 for v in present.values() if v)
    if set_count == 0:
        return None
    if set_count != len(_OIDC_ENV_VARS):
        missing = [name for name, v in present.items() if not v]
        raise OfficeError(
            code=EXIT_ENV_ERROR,
            message=f"OIDC is partially configured; missing: {', '.join(missing)}",
            remediation=("set all five OIDC_*/SESSION_SECRET vars, or unset all to disable SSO"),
        )
    return OIDCConfig(
        issuer=present["OIDC_ISSUER"],
        client_id=present["OIDC_CLIENT_ID"],
        client_secret=present["OIDC_CLIENT_SECRET"],
        redirect_url=present["OIDC_REDIRECT_URL"],
        session_secret=present["SESSION_SECRET"],
    )


def install_session_middleware(app: Any, oidc: OIDCConfig) -> None:
    """Register Starlette's signed-cookie SessionMiddleware on ``app``."""
    from starlette.middleware.sessions import SessionMiddleware

    app.add_middleware(
        SessionMiddleware,
        secret_key=oidc.session_secret,
        same_site="lax",
        https_only=True,
        session_cookie="office_session",
    )


def register_auth_routes(app: Any, oidc: OIDCConfig, roles: RolesConfig) -> None:
    """Register ``/auth/login``, ``/auth/callback``, ``/auth/logout``.

    The OIDC client is constructed via :class:`authlib.integrations.starlette_client.OAuth`.
    ``next`` is whitelist-validated to prevent open-redirect.
    """
    from authlib.integrations.starlette_client import OAuth
    from fastapi import Request
    from fastapi.responses import RedirectResponse

    oauth = OAuth()
    oauth.register(
        name="office",
        client_id=oidc.client_id,
        client_secret=oidc.client_secret,
        server_metadata_url=f"{oidc.issuer.rstrip('/')}/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

    @app.get("/auth/login")
    async def auth_login(request: Request, next: str = "/"):
        request.session["next"] = _safe_next(next)
        client = oauth.create_client("office")
        return await client.authorize_redirect(request, oidc.redirect_url)

    @app.get("/auth/callback")
    async def auth_callback(request: Request):
        client = oauth.create_client("office")
        token = await client.authorize_access_token(request)
        userinfo = token.get("userinfo") or {}
        email = (userinfo.get("email") or "").strip()
        if not email:
            # The IdP didn't return an email claim — surface a clear 400
            # rather than letting the session land empty.
            raise OfficeError(
                code=EXIT_ENV_ERROR,
                message="OIDC token has no email claim",
                remediation="check the IdP scope configuration (need 'openid email')",
            )
        role = role_for_email(roles, email)
        request.session[_SESSION_USER_KEY] = {"email": email, "role": role}
        return RedirectResponse(url=request.session.pop("next", "/"), status_code=302)

    @app.post("/auth/logout")
    async def auth_logout(request: Request):
        request.session.pop(_SESSION_USER_KEY, None)
        return RedirectResponse(url="/", status_code=302)


def current_user(request: Any, *, oidc: OIDCConfig | None) -> dict[str, str] | None:
    """Return the ``{email, role}`` dict for this request, or ``None``.

    With OIDC enabled, the session is the sole source. Without OIDC,
    the ``X-Test-Role`` header (if present) yields a synthetic user —
    this is intentional so unit tests can drive role-aware behavior
    without sessions.
    """
    if oidc is not None:
        try:
            user = request.session.get(_SESSION_USER_KEY)
        except (AttributeError, AssertionError):
            # ``session`` is unavailable when SessionMiddleware is missing.
            return None
        return user if user else None
    test_role = request.headers.get(_TEST_ROLE_HEADER, "").strip().lower()
    if test_role:
        return {"email": f"test+{test_role}@example.com", "role": test_role}
    return None


def role_from_user(user: dict[str, str] | None) -> str:
    """Default to viewer when there's no user (anonymous browsing)."""
    if not user:
        return VIEWER
    return user.get("role") or VIEWER


def _safe_next(raw: str) -> str:
    """Whitelist-validate a ``next`` URL.

    Returns ``"/"`` if ``raw`` is missing, doesn't start with ``/``, or
    starts with ``//`` / ``/\\`` (which would target an external host).
    Anti-open-redirect.
    """
    if not raw or not raw.startswith("/"):
        return "/"
    if raw.startswith("//") or raw.startswith("/\\"):
        return "/"
    return raw
