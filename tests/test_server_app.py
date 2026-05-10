"""End-to-end tests for the FastAPI seat-map server.

Uses ``fastapi.testclient.TestClient`` against a service built from the
project fixtures. No real network or Slack involvement.
"""

from __future__ import annotations

from itertools import count
from pathlib import Path

import pytest

pytest.importorskip("fastapi")  # skip cleanly if the [web] extra isn't installed

from fastapi.testclient import TestClient  # noqa: E402

from office_cli.people import Employee  # noqa: E402
from office_cli.people.bamboohr import BambooHRDirectory  # noqa: E402
from office_cli.seats import build_service  # noqa: E402
from office_cli.server import build_app  # noqa: E402
from tests.test_bamboohr_directory import FakeBambooHRClient  # noqa: E402


def _service(data_dir: Path):
    counter = count(1)

    def clock() -> str:
        return f"2026-05-01T00:00:{next(counter):02d}Z"

    s = build_service(data_dir)
    s._clock = clock  # noqa: SLF001 — deterministic for tests
    return s


def _client(data_dir: Path) -> TestClient:
    return TestClient(build_app(_service(data_dir), data_dir=data_dir))


def test_get_offices(data_dir: Path) -> None:
    with _client(data_dir) as c:
        r = c.get("/api/offices")
        assert r.status_code == 200
        body = r.json()
        assert {o["id"] for o in body["offices"]} == {"tlv"}
        assert body["offices"][0]["floors"] == [{"id": "tlv-floor-5", "status": "active"}]


def test_get_seats_returns_all(data_dir: Path) -> None:
    s = _service(data_dir)
    s.assign("5-T-01", "alice@example.com")
    with TestClient(build_app(s, data_dir=data_dir)) as c:
        r = c.get("/api/seats")
        assert r.status_code == 200
        body = r.json()
        assert body["office"] is None
        seats = {seat["seat_id"]: seat for seat in body["seats"]}
        # Every declared seat in the fixture surfaces, occupied or not.
        assert "5-T-01" in seats
        assert seats["5-T-01"]["employee_email"] == "alice@example.com"
        assert seats["5-T-01"]["floor"] == "tlv-floor-5"


def test_get_seats_filters_by_office(data_dir: Path) -> None:
    with _client(data_dir) as c:
        r = c.get("/api/seats?office=tlv")
        assert r.status_code == 200
        body = r.json()
        assert body["office"] == "tlv"
        assert {seat["floor"] for seat in body["seats"]} == {"tlv-floor-5"}


def test_get_seats_unknown_office_404(data_dir: Path) -> None:
    with _client(data_dir) as c:
        r = c.get("/api/seats?office=nope")
        assert r.status_code == 404


def test_get_floor_returns_merged_view(data_dir: Path) -> None:
    s = _service(data_dir)
    s.assign("5-T-01", "alice@example.com")
    with TestClient(build_app(s, data_dir=data_dir)) as c:
        r = c.get("/api/floors/tlv-floor-5")
        assert r.status_code == 200
        body = r.json()
        assert body["floor"]["id"] == "tlv-floor-5"
        assert body["floor"]["office"] == "tlv"
        assert body["svg_url"] == "/svgs/tlv-floor-5.svg"
        seats = {seat["seat_id"]: seat for seat in body["seats"]}
        assert seats["5-T-01"]["employee_email"] == "alice@example.com"
        assert seats["5-T-01"]["hidden"] is False
        # Vacant seats render with employee_email=null, never the empty string.
        assert seats["5-T-02"]["employee_email"] is None


def test_hidden_seat_is_redacted_server_side(data_dir: Path) -> None:
    """The frontend must never see the email or notes for hidden=True rows."""
    s = _service(data_dir)
    s.assign("5-T-01", "exec@example.com", hidden=True, note="exec seat")
    with TestClient(build_app(s, data_dir=data_dir)) as c:
        body = c.get("/api/floors/tlv-floor-5").json()
    seats = {x["seat_id"]: x for x in body["seats"]}
    row = seats["5-T-01"]
    assert row["hidden"] is True
    assert row["employee_email"] == "(private)"
    assert row["notes"] == ""


def test_autovacate_flows_through(data_dir: Path) -> None:
    """Stage-3 auto-vacate filter must apply to API responses too."""
    bamboo_client = FakeBambooHRClient([Employee(email="alice@example.com")])
    directory = BambooHRDirectory(bamboo_client, cache_ttl_seconds=0)
    s = _service(data_dir)
    s.directory = directory
    s.assign("5-T-01", "alice@example.com")

    bamboo_client.employees = []
    directory.invalidate()

    with TestClient(build_app(s, data_dir=data_dir)) as c:
        body = c.get("/api/floors/tlv-floor-5").json()
    seats = {x["seat_id"]: x for x in body["seats"]}
    # The auto-vacate filter clears employee_email — the API surface
    # reports vacant.
    assert seats["5-T-01"]["employee_email"] is None


def test_get_floor_with_as_of_filters(data_dir: Path) -> None:
    """Stage 6 — the server honors ``?as_of=`` and pipes it into the service."""
    s = _service(data_dir)
    s.assign("5-T-01", "alice@example.com", effective_from="2026-07-01")
    with TestClient(build_app(s, data_dir=data_dir)) as c:
        # Before the window: row renders vacant.
        body = c.get("/api/floors/tlv-floor-5?as_of=2026-06-30").json()
        seats = {x["seat_id"]: x for x in body["seats"]}
        assert seats["5-T-01"]["employee_email"] is None
        assert body["as_of"] == "2026-06-30"
        # Inside the window: row visible.
        body = c.get("/api/floors/tlv-floor-5?as_of=2026-07-15").json()
        seats = {x["seat_id"]: x for x in body["seats"]}
        assert seats["5-T-01"]["employee_email"] == "alice@example.com"
        # No ``as_of`` at all: as_of in response is null.
        body = c.get("/api/floors/tlv-floor-5").json()
        assert body["as_of"] is None


def test_get_floor_defaults_to_today_filter(data_dir: Path) -> None:
    """No ``as_of`` query param → server defaults to today (using its clock)."""
    s = _service(data_dir)
    s.assign("5-T-01", "alice@example.com", effective_from="2099-01-01")
    with TestClient(build_app(s, data_dir=data_dir)) as c:
        body = c.get("/api/floors/tlv-floor-5").json()
    seats = {x["seat_id"]: x for x in body["seats"]}
    # The future-dated row is hidden as vacant under the default-today filter.
    assert seats["5-T-01"]["employee_email"] is None
    # When the caller did not pass ``as_of``, the response echoes ``null`` so
    # the frontend knows not to surface the banner.
    assert body["as_of"] is None


def test_get_floor_accepts_camelcase_asof(data_dir: Path) -> None:
    """``?asOf=`` is honored alongside ``?as_of=`` for direct-API callers."""
    s = _service(data_dir)
    s.assign("5-T-01", "alice@example.com", effective_from="2026-07-01")
    with TestClient(build_app(s, data_dir=data_dir)) as c:
        body = c.get("/api/floors/tlv-floor-5?asOf=2026-07-15").json()
    seats = {x["seat_id"]: x for x in body["seats"]}
    assert seats["5-T-01"]["employee_email"] == "alice@example.com"
    assert body["as_of"] == "2026-07-15"


def test_get_floor_rejects_malformed_as_of(data_dir: Path) -> None:
    with _client(data_dir) as c:
        r = c.get("/api/floors/tlv-floor-5?as_of=tomorrow")
        assert r.status_code == 400
        body = r.json()
        assert "as_of" in body["error"]
        assert "remediation" in body


def test_unknown_floor_returns_404(data_dir: Path) -> None:
    with _client(data_dir) as c:
        r = c.get("/api/floors/no-such-floor")
        assert r.status_code == 404
        body = r.json()
        # FastAPI puts handler-thrown HTTPException details under "detail".
        assert "unknown floor" in body["detail"]["error"]
        assert "remediation" in body["detail"]


def test_root_redirects_to_first_floor(data_dir: Path) -> None:
    with _client(data_dir) as c:
        r = c.get("/", follow_redirects=False)
        assert r.status_code in (302, 307)
        assert r.headers["location"] == "/offices/tlv/floors/tlv-floor-5"


def test_spa_shell_serves_html(data_dir: Path) -> None:
    with _client(data_dir) as c:
        r = c.get("/offices/tlv/floors/tlv-floor-5")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        assert "<title>office — seat map</title>" in r.text
        assert '<script type="module" src="/static/app.js">' in r.text


def test_spa_shell_validates_office_floor(data_dir: Path) -> None:
    with _client(data_dir) as c:
        # Wrong office id for an existing floor.
        r = c.get("/offices/sf/floors/tlv-floor-5")
        assert r.status_code == 404
        # Wrong floor entirely.
        r2 = c.get("/offices/tlv/floors/no-such-floor")
        assert r2.status_code == 404


def test_static_assets_served(data_dir: Path) -> None:
    with _client(data_dir) as c:
        for path in ("/static/app.css", "/static/app.js", "/static/vendor/fuse.js"):
            r = c.get(path)
            assert r.status_code == 200, path


def test_floor_svg_served_via_static_mount(data_dir: Path) -> None:
    with _client(data_dir) as c:
        r = c.get("/svgs/tlv-floor-5.svg")
        assert r.status_code == 200
        # Content-type may be image/svg+xml or application/xml depending on
        # platform; both are acceptable. Just check it's not html.
        assert "html" not in r.headers["content-type"]
        assert "<svg" in r.text


def test_short_floor_url_redirects_to_canonical_spa(data_dir: Path) -> None:
    """Slack's deep-link button (Stage 4) builds /floors/{id}?seat=X URLs.

    The web server resolves them to /offices/{office}/floors/{id}?seat=X
    so callers do not need to know the office id.
    """
    with _client(data_dir) as c:
        r = c.get("/floors/tlv-floor-5?seat=5-T-01", follow_redirects=False)
        assert r.status_code in (302, 307)
        assert r.headers["location"] == "/offices/tlv/floors/tlv-floor-5?seat=5-T-01"

        # Bare path, no query.
        r2 = c.get("/floors/tlv-floor-5", follow_redirects=False)
        assert r2.status_code in (302, 307)
        assert r2.headers["location"] == "/offices/tlv/floors/tlv-floor-5"

        # Unknown floor surfaces 404, not a redirect to a broken URL.
        r3 = c.get("/floors/no-such-floor", follow_redirects=False)
        assert r3.status_code == 404


def test_hidden_seat_redacts_notes_when_vacant(data_dir: Path) -> None:
    """Qodo Q4: a hidden=TRUE row with no email must still scrub notes."""
    s = _service(data_dir)
    # Manually craft a hidden-but-vacant row by writing through the store
    # (`assign` requires an email, so we build the Assignment directly).
    from office_cli.seats import Assignment

    s.store.upsert(
        Assignment(
            seat_id="5-T-01",
            floor="tlv-floor-5",
            employee_email="",
            hidden=True,
            notes="reserved for visiting exec",
        )
    )
    with TestClient(build_app(s, data_dir=data_dir)) as c:
        body = c.get("/api/floors/tlv-floor-5").json()
    seats = {x["seat_id"]: x for x in body["seats"]}
    row = seats["5-T-01"]
    assert row["hidden"] is True
    assert row["employee_email"] is None
    assert row["notes"] == ""


def test_build_app_without_extra_raises(monkeypatch: pytest.MonkeyPatch, data_dir: Path) -> None:
    """OfficeError surfaces with a clear remediation if FastAPI is missing."""
    import builtins

    real_import = builtins.__import__

    def block_fastapi(name, *args, **kwargs):
        if name.startswith("fastapi"):
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", block_fastapi)
    from office_cli.cli._errors import OfficeError

    s = _service(data_dir)
    with pytest.raises(OfficeError) as exc:
        build_app(s, data_dir=data_dir)
    assert "fastapi is not installed" in exc.value.message
    assert "office-cli[web]" in exc.value.remediation
