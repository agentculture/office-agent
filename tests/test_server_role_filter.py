"""End-to-end role-aware redaction tests via TestClient.

Auth-disabled mode is the default — the ``X-Test-Role`` header drives
which role the request is treated as. Production sets OIDC env and
this header is ignored (verified separately in
``test_server_auth.py``).
"""

from __future__ import annotations

from itertools import count
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from office_cli.seats import build_service  # noqa: E402
from office_cli.server import build_app  # noqa: E402


def _service(data_dir: Path):
    counter = count(1)

    def clock() -> str:
        return f"2026-05-01T00:00:{next(counter):02d}Z"

    s = build_service(data_dir)
    s._clock = clock  # noqa: SLF001
    return s


def _client(data_dir: Path) -> TestClient:
    return TestClient(build_app(_service(data_dir), data_dir=data_dir))


def test_default_no_header_is_viewer(data_dir: Path) -> None:
    """No ``X-Test-Role`` header → viewer (default redaction applies)."""
    s = _service(data_dir)
    s.assign("5-T-01", "exec@example.com", hidden=True, note="exec note")
    with TestClient(build_app(s, data_dir=data_dir)) as c:
        body = c.get("/api/floors/tlv-floor-5").json()
    seats = {x["seat_id"]: x for x in body["seats"]}
    assert seats["5-T-01"]["employee_email"] == "(private)"
    assert seats["5-T-01"]["notes"] == ""


def test_viewer_header_redacts(data_dir: Path) -> None:
    s = _service(data_dir)
    s.assign("5-T-01", "exec@example.com", hidden=True)
    with TestClient(build_app(s, data_dir=data_dir)) as c:
        body = c.get(
            "/api/floors/tlv-floor-5",
            headers={"X-Test-Role": "viewer"},
        ).json()
    seats = {x["seat_id"]: x for x in body["seats"]}
    assert seats["5-T-01"]["employee_email"] == "(private)"
    # Response carries the user identity for the SPA to render.
    assert body["user"]["role"] == "viewer"


def test_editor_header_sees_full(data_dir: Path) -> None:
    s = _service(data_dir)
    s.assign("5-T-01", "exec@example.com", hidden=True, note="exec note")
    with TestClient(build_app(s, data_dir=data_dir)) as c:
        body = c.get(
            "/api/floors/tlv-floor-5",
            headers={"X-Test-Role": "editor"},
        ).json()
    seats = {x["seat_id"]: x for x in body["seats"]}
    assert seats["5-T-01"]["employee_email"] == "exec@example.com"
    assert seats["5-T-01"]["notes"] == "exec note"
    assert body["user"]["role"] == "editor"


def test_planning_header_sees_full(data_dir: Path) -> None:
    """Planning is editor-equivalent in v1."""
    s = _service(data_dir)
    s.assign("5-T-01", "exec@example.com", hidden=True)
    with TestClient(build_app(s, data_dir=data_dir)) as c:
        body = c.get(
            "/api/floors/tlv-floor-5",
            headers={"X-Test-Role": "planning"},
        ).json()
    seats = {x["seat_id"]: x for x in body["seats"]}
    assert seats["5-T-01"]["employee_email"] == "exec@example.com"


def test_non_hidden_unaffected_by_role(data_dir: Path) -> None:
    s = _service(data_dir)
    s.assign("5-T-01", "alice@example.com")
    with TestClient(build_app(s, data_dir=data_dir)) as c:
        for role in ("viewer", "editor", "planning"):
            body = c.get(
                "/api/floors/tlv-floor-5",
                headers={"X-Test-Role": role},
            ).json()
            seats = {x["seat_id"]: x for x in body["seats"]}
            assert seats["5-T-01"]["employee_email"] == "alice@example.com"


def test_redacted_field_in_json(data_dir: Path) -> None:
    """Stage 7 — the API response carries a ``redacted: bool`` flag.

    Frontend clients use it to render ``"(private)"`` vs ``"(vacant)"``
    correctly under the new Stage 7 semantics where ``hidden=True`` no
    longer implies viewer-style redaction.
    """
    s = _service(data_dir)
    s.assign("5-T-01", "exec@example.com", hidden=True)
    s.assign("5-T-02", "alice@example.com")
    with TestClient(build_app(s, data_dir=data_dir)) as c:
        viewer_body = c.get("/api/floors/tlv-floor-5", headers={"X-Test-Role": "viewer"}).json()
        editor_body = c.get("/api/floors/tlv-floor-5", headers={"X-Test-Role": "editor"}).json()
    viewer_seats = {x["seat_id"]: x for x in viewer_body["seats"]}
    editor_seats = {x["seat_id"]: x for x in editor_body["seats"]}
    # Hidden + viewer → redacted: True.
    assert viewer_seats["5-T-01"]["redacted"] is True
    # Hidden + editor → redacted: False (full visibility).
    assert editor_seats["5-T-01"]["redacted"] is False
    # Non-hidden → redacted: False, regardless of role.
    assert viewer_seats["5-T-02"]["redacted"] is False
    assert editor_seats["5-T-02"]["redacted"] is False


def test_build_app_auto_resolves_roles_from_yaml(tmp_path: Path) -> None:
    """``build_app(data_dir=...)`` reads ``roles:`` from ``data/offices.yaml``."""
    import shutil

    src = Path(__file__).parent / "fixtures"
    target = tmp_path / "office-data"
    shutil.copytree(src, target)
    (target / "seats").mkdir(exist_ok=True)
    # Append a roles block to the fixture YAML.
    yaml_path = target / "data" / "offices.yaml"
    yaml_path.write_text(
        yaml_path.read_text(encoding="utf-8") + "\nroles:\n  editor:\n    - alice@example.com\n",
        encoding="utf-8",
    )
    s = _service(target)
    s.assign("5-T-01", "exec@example.com", hidden=True)
    # No explicit ``roles=`` — build_app auto-resolves from data_dir.
    with TestClient(build_app(s, data_dir=target)) as c:
        # No header → anonymous → viewer → redacted.
        body = c.get("/api/floors/tlv-floor-5").json()
    seats = {x["seat_id"]: x for x in body["seats"]}
    assert seats["5-T-01"]["redacted"] is True


def test_user_field_null_when_no_session(data_dir: Path) -> None:
    s = _service(data_dir)
    with TestClient(build_app(s, data_dir=data_dir)) as c:
        body = c.get("/api/floors/tlv-floor-5").json()
    assert body["user"] is None


def test_sso_redirects_unauth_browser(data_dir: Path) -> None:
    """Stage 7 acceptance — unauth browser → 302 to ``/auth/login?next=...``.

    Uses a stub OIDC config; we never reach the real IdP because the
    spa_shell redirect happens before any auth-route call.
    """
    pytest.importorskip("authlib")
    from office_cli.server._auth import OIDCConfig

    oidc = OIDCConfig(
        issuer="https://idp.example.com",
        client_id="cid",
        client_secret="csecret",
        redirect_url="https://office.example.com/auth/callback",
        session_secret="x" * 32,
    )
    s = _service(data_dir)
    with TestClient(build_app(s, data_dir=data_dir, oidc=oidc)) as c:
        r = c.get("/offices/tlv/floors/tlv-floor-5", follow_redirects=False)
    assert r.status_code == 302
    # ``next`` is URL-encoded so embedded ``&`` / ``?`` / ``=`` round-trip.
    assert r.headers["location"] == "/auth/login?next=%2Foffices%2Ftlv%2Ffloors%2Ftlv-floor-5"


def test_sso_redirect_preserves_query_params(data_dir: Path) -> None:
    """Qodo Q1 on PR #20 — original URL with ``&``-joined query params
    must round-trip through the redirect intact.
    """
    pytest.importorskip("authlib")
    from office_cli.server._auth import OIDCConfig

    oidc = OIDCConfig(
        issuer="https://idp.example.com",
        client_id="cid",
        client_secret="csecret",
        redirect_url="https://office.example.com/auth/callback",
        session_secret="x" * 32,
    )
    s = _service(data_dir)
    with TestClient(build_app(s, data_dir=data_dir, oidc=oidc)) as c:
        r = c.get(
            "/offices/tlv/floors/tlv-floor-5?seat=5-T-01&asOf=2026-07-01",
            follow_redirects=False,
        )
    assert r.status_code == 302
    # Decode the next param to check the original URL survives.
    from urllib.parse import parse_qs, urlparse

    location = r.headers["location"]
    next_param = parse_qs(urlparse(location).query)["next"][0]
    assert next_param == "/offices/tlv/floors/tlv-floor-5?seat=5-T-01&asOf=2026-07-01"


def test_sso_test_role_header_ignored_when_oidc_enabled(data_dir: Path) -> None:
    """The ``X-Test-Role`` escape hatch must NOT work in production mode."""
    pytest.importorskip("authlib")
    from office_cli.server._auth import OIDCConfig

    oidc = OIDCConfig(
        issuer="https://idp.example.com",
        client_id="cid",
        client_secret="csecret",
        redirect_url="https://office.example.com/auth/callback",
        session_secret="x" * 32,
    )
    s = _service(data_dir)
    s.assign("5-T-01", "exec@example.com", hidden=True)
    with TestClient(build_app(s, data_dir=data_dir, oidc=oidc)) as c:
        body = c.get(
            "/api/floors/tlv-floor-5",
            headers={"X-Test-Role": "editor"},
        ).json()
    seats = {x["seat_id"]: x for x in body["seats"]}
    # With OIDC enabled and no session, the caller is anonymous → viewer.
    # The X-Test-Role header is ignored; redaction stays in force.
    assert seats["5-T-01"]["employee_email"] == "(private)"
