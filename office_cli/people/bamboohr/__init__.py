"""BambooHR-backed :class:`EmployeeDirectory`.

Importing this subpackage does not import ``requests`` at module-load
time: ``RequestsBambooHRClient`` performs a lazy import on first call.
That way, installations without the ``[bamboohr]`` extra installed can
still import :mod:`office_cli.people` and use the default
:class:`StubDirectory`.
"""

from __future__ import annotations

from office_cli.people.bamboohr._client import (
    BambooHRClient,
    RequestsBambooHRClient,
)
from office_cli.people.bamboohr._directory import BambooHRDirectory

__all__ = ["BambooHRClient", "BambooHRDirectory", "RequestsBambooHRClient"]
