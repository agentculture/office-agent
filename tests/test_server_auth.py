"""Tests for the SSO config resolution + auth middleware (Stage 7)."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from office_cli.cli._errors import EXIT_ENV_ERROR, OfficeError  # noqa: E402
from office_cli.server._auth import OIDCConfig, resolve_oidc  # noqa: E402

_ALL_VARS = {
    "OIDC_ISSUER": "https://idp.example.com",
    "OIDC_CLIENT_ID": "office-agent",
    "OIDC_CLIENT_SECRET": "shh",
    "OIDC_REDIRECT_URL": "https://office.example.com/auth/callback",
    "SESSION_SECRET": "x" * 32,
}


def test_resolve_returns_none_when_empty() -> None:
    assert resolve_oidc({}) is None


def test_resolve_returns_config_when_all_present() -> None:
    cfg = resolve_oidc(_ALL_VARS)
    assert isinstance(cfg, OIDCConfig)
    assert cfg.issuer == "https://idp.example.com"
    assert cfg.client_id == "office-agent"


def test_resolve_rejects_partial_config() -> None:
    partial = dict(_ALL_VARS)
    del partial["OIDC_CLIENT_SECRET"]
    with pytest.raises(OfficeError) as exc:
        resolve_oidc(partial)
    assert exc.value.code == EXIT_ENV_ERROR
    assert "OIDC_CLIENT_SECRET" in exc.value.message


def test_resolve_treats_blank_as_missing() -> None:
    """All-blank → None; some-blank → partial-config error."""
    assert resolve_oidc(dict.fromkeys(_ALL_VARS, "")) is None
    partial = dict(_ALL_VARS)
    partial["SESSION_SECRET"] = "   "
    with pytest.raises(OfficeError):
        resolve_oidc(partial)


def test_session_cookie_secure_default_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """``OIDC_COOKIE_SECURE`` defaults to true (production-secure)."""
    from starlette.applications import Starlette

    from office_cli.server._auth import install_session_middleware

    monkeypatch.delenv("OIDC_COOKIE_SECURE", raising=False)
    cfg = OIDCConfig(
        issuer="https://idp.example.com",
        client_id="cid",
        client_secret="csecret",
        redirect_url="https://office.example.com/auth/callback",
        session_secret="x" * 32,
    )
    app = Starlette()
    install_session_middleware(app, cfg)
    # Inspect the user_middleware list — Starlette stores them in order.
    secure_flags = [
        mw.kwargs.get("https_only")
        for mw in app.user_middleware
        if mw.cls.__name__ == "SessionMiddleware"
    ]
    assert secure_flags == [True]


def test_session_cookie_secure_opt_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """``OIDC_COOKIE_SECURE=false`` lets staging (HTTP) work without a loop."""
    from starlette.applications import Starlette

    from office_cli.server._auth import install_session_middleware

    monkeypatch.setenv("OIDC_COOKIE_SECURE", "false")
    cfg = OIDCConfig(
        issuer="https://idp.example.com",
        client_id="cid",
        client_secret="csecret",
        redirect_url="https://office.example.com/auth/callback",
        session_secret="x" * 32,
    )
    app = Starlette()
    install_session_middleware(app, cfg)
    secure_flags = [
        mw.kwargs.get("https_only")
        for mw in app.user_middleware
        if mw.cls.__name__ == "SessionMiddleware"
    ]
    assert secure_flags == [False]
