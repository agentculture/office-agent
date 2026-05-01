"""Tests for the BambooHR-backed EmployeeDirectory.

A ``FakeBambooHRClient`` plays the role of the real REST shim; no
network calls happen. TTL behavior is exercised with an injected clock;
fail-open semantics are verified by making the fake raise after the
first refresh.
"""

from __future__ import annotations

from typing import Iterable

import pytest

from office_cli.cli._errors import OfficeError
from office_cli.people import Employee
from office_cli.people.bamboohr import BambooHRDirectory, RequestsBambooHRClient


class FakeBambooHRClient:
    def __init__(self, employees: Iterable[Employee] = ()) -> None:
        self.employees = list(employees)
        self.call_count = 0
        self.next_error: Exception | None = None

    def fetch_directory(self) -> list[Employee]:
        self.call_count += 1
        if self.next_error is not None:
            err = self.next_error
            self.next_error = None
            raise err
        return list(self.employees)


def _emp(email: str, name: str = "") -> Employee:
    return Employee(email=email, name=name or email)


def test_get_returns_active_employee() -> None:
    client = FakeBambooHRClient([_emp("alice@x"), _emp("bob@x")])
    directory = BambooHRDirectory(client, cache_ttl_seconds=99999)
    assert directory.is_active("alice@x") is True
    assert directory.get("alice@x").email == "alice@x"
    assert directory.is_active("ghost@x") is False
    assert directory.get("ghost@x") is None


def test_empty_email_is_inactive() -> None:
    client = FakeBambooHRClient([_emp("alice@x")])
    directory = BambooHRDirectory(client, cache_ttl_seconds=99999)
    assert directory.is_active("") is False
    assert directory.get("") is None


def test_cache_within_ttl_avoids_refetch() -> None:
    client = FakeBambooHRClient([_emp("alice@x")])
    directory = BambooHRDirectory(client, cache_ttl_seconds=10, clock=lambda: 0.0)
    directory.is_active("alice@x")
    directory.is_active("alice@x")
    directory.is_active("alice@x")
    assert client.call_count == 1


def test_refresh_after_ttl() -> None:
    client = FakeBambooHRClient([_emp("alice@x")])
    now = [0.0]
    directory = BambooHRDirectory(client, cache_ttl_seconds=10, clock=lambda: now[0])
    directory.is_active("alice@x")
    now[0] = 5.0
    directory.is_active("alice@x")  # still cached
    now[0] = 100.0
    directory.is_active("alice@x")  # refresh
    assert client.call_count == 2


def test_offboarding_observed_after_ttl() -> None:
    """The killer feature: after TTL, removed employees become inactive."""
    client = FakeBambooHRClient([_emp("alice@x")])
    now = [0.0]
    directory = BambooHRDirectory(client, cache_ttl_seconds=10, clock=lambda: now[0])
    assert directory.is_active("alice@x") is True
    client.employees = []  # Alice offboarded in BambooHR
    assert directory.is_active("alice@x") is True  # still cached
    now[0] = 100.0
    assert directory.is_active("alice@x") is False  # cache refreshed


def test_failopen_serves_stale_cache(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Per #7: BambooHR outages must not stop people finding their seats."""
    client = FakeBambooHRClient([_emp("alice@x")])
    now = [0.0]
    directory = BambooHRDirectory(client, cache_ttl_seconds=10, clock=lambda: now[0])
    directory.is_active("alice@x")  # seed cache
    client.next_error = ConnectionError("BambooHR down")
    now[0] = 100.0
    # Cache is stale; refresh fails. Must serve cached "alice@x".
    assert directory.is_active("alice@x") is True
    err = capsys.readouterr().err
    assert "BambooHR fetch failed" in err
    assert "serving cached directory" in err


def test_failed_refresh_rate_limits_within_ttl(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Copilot/Qodo: a sustained outage must not refetch on every is_active call.

    `SeatService.list_seats` calls `is_active` per seat, so a stale cache
    plus a failing BambooHR would otherwise issue N requests + N stderr
    diagnostics for an N-seat office.
    """
    client = FakeBambooHRClient([_emp("alice@x")])
    now = [0.0]
    directory = BambooHRDirectory(client, cache_ttl_seconds=10, clock=lambda: now[0])
    directory.is_active("alice@x")  # seed cache
    capsys.readouterr()
    assert client.call_count == 1

    # Cache is now stale; BambooHR is down.
    now[0] = 100.0
    client.next_error = ConnectionError("BambooHR down")
    directory.is_active("alice@x")
    err1 = capsys.readouterr().err
    assert "BambooHR fetch failed" in err1
    assert client.call_count == 2

    # Two more is_active calls within the TTL window must not refetch and
    # must not re-emit the diagnostic.
    client.next_error = ConnectionError("still down")
    directory.is_active("alice@x")
    directory.is_active("bob@x")
    assert client.call_count == 2  # rate-limited
    assert capsys.readouterr().err == ""

    # After another TTL window elapses, we try again exactly once.
    now[0] = 220.0
    client.next_error = ConnectionError("still down")
    directory.is_active("alice@x")
    directory.is_active("bob@x")
    assert client.call_count == 3


def test_failclosed_when_no_cache_yet() -> None:
    """First fetch failure must surface as OfficeError; we have nothing to serve."""
    client = FakeBambooHRClient()
    client.next_error = ConnectionError("BambooHR down")
    directory = BambooHRDirectory(client, cache_ttl_seconds=10)
    with pytest.raises(OfficeError) as exc:
        directory.is_active("alice@x")
    assert exc.value.code == 2  # EXIT_ENV_ERROR
    assert "BambooHR" in exc.value.message


def test_invalidate_forces_next_refresh() -> None:
    client = FakeBambooHRClient([_emp("alice@x")])
    directory = BambooHRDirectory(client, cache_ttl_seconds=99999, clock=lambda: 0.0)
    directory.is_active("alice@x")
    directory.invalidate()
    directory.is_active("alice@x")
    assert client.call_count == 2


def test_requests_client_validates_required_inputs() -> None:
    with pytest.raises(OfficeError) as exc:
        RequestsBambooHRClient(subdomain="", api_token="x")
    assert "subdomain" in exc.value.message
    with pytest.raises(OfficeError) as exc:
        RequestsBambooHRClient(subdomain="x", api_token="")
    assert "API token" in exc.value.message


def test_requests_missing_raises_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """If requests isn't installed, RequestsBambooHRClient surfaces OfficeError."""
    import builtins

    real_import = builtins.__import__

    def block_requests(name, *args, **kwargs):
        if name == "requests":
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", block_requests)
    with pytest.raises(OfficeError) as exc:
        RequestsBambooHRClient(subdomain="x", api_token="t")
    assert "requests is not installed" in exc.value.message
