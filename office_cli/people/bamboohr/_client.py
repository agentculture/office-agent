"""Thin shim over the BambooHR REST API.

The :class:`BambooHRClient` Protocol exposes only the one operation the
directory needs (``fetch_directory``). The directory is unit-tested
against a ``FakeBambooHRClient`` so the test suite never needs real
credentials. :class:`RequestsBambooHRClient` is the production
implementation — ``requests`` is imported lazily so the parent package
loads without the ``[bamboohr]`` extra.

The directory endpoint ``GET /v1/employees/directory`` (BambooHR
docs: https://documentation.bamboohr.com/reference/get-employees-directory-1)
returns only employees whose status is "Active" — anyone marked
terminated drops from the response. That's exactly the auto-vacate
signal for v1: presence in the directory implies active employment.
"""

from __future__ import annotations

from typing import Protocol

from office_cli.cli._errors import EXIT_ENV_ERROR, OfficeError
from office_cli.people._stub import Employee


class BambooHRClient(Protocol):
    def fetch_directory(self) -> list[Employee]:
        """Return the list of currently-active employees, keyed by email."""


class RequestsBambooHRClient:
    """Production :class:`BambooHRClient` implementation using ``requests``."""

    def __init__(
        self,
        subdomain: str,
        api_token: str,
        *,
        timeout_seconds: float = 10.0,
        base_url: str | None = None,
    ) -> None:
        # Validate inputs first so misconfiguration surfaces with a clear
        # remediation even when ``requests`` is missing.
        if not subdomain:
            raise OfficeError(
                code=EXIT_ENV_ERROR,
                message="BambooHR subdomain is empty",
                remediation="set BAMBOOHR_SUBDOMAIN or directory.bamboohr.subdomain",
            )
        if not api_token:
            raise OfficeError(
                code=EXIT_ENV_ERROR,
                message="BambooHR API token is empty",
                remediation="set BAMBOOHR_API_TOKEN (the token must not be committed)",
            )
        try:
            import requests  # noqa: F401 — runtime check
        except ImportError as err:
            raise OfficeError(
                code=EXIT_ENV_ERROR,
                message="requests is not installed",
                remediation=("install the bamboohr extra: uv tool install 'office-cli[bamboohr]'"),
            ) from err
        self._subdomain = subdomain
        self._api_token = api_token
        self._timeout = timeout_seconds
        self._base_url = base_url or (f"https://api.bamboohr.com/api/gateway.php/{subdomain}/v1")

    def fetch_directory(self) -> list[Employee]:
        import requests

        resp = requests.get(
            f"{self._base_url}/employees/directory",
            auth=(self._api_token, "x"),
            headers={"Accept": "application/json"},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        out: list[Employee] = []
        for row in payload.get("employees") or []:
            email = (row.get("workEmail") or "").strip()
            if not email:
                continue
            out.append(
                Employee(
                    email=email,
                    name=row.get("displayName") or "",
                    role=row.get("jobTitle") or "",
                    photo_url=row.get("photoUrl") or "",
                )
            )
        return out
