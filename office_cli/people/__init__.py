"""People surface — Stage 1 stub.

The real source of truth for employees is BambooHR, pulled live and cached
five minutes. Stage 1 stubs that with :class:`StubDirectory`, which trusts
whatever email it is handed and never persists anything.
"""

from __future__ import annotations

from office_cli.people._stub import Employee, EmployeeDirectory, StubDirectory

__all__ = ["Employee", "EmployeeDirectory", "StubDirectory"]
