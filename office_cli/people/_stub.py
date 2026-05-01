"""Employee model + directory Protocol + a no-op stub."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Employee:
    email: str
    name: str = ""
    role: str = ""
    photo_url: str = ""

    @property
    def is_active(self) -> bool:
        # Real directories will compute this against BambooHR's offboarding
        # state. The stub treats every email as active.
        return True


class EmployeeDirectory(Protocol):
    def get(self, email: str) -> Employee | None:
        """Return employee details for ``email`` or ``None`` if unknown."""

    def is_active(self, email: str) -> bool:
        """``True`` if the employee is currently employed (drives auto-vacate)."""


class StubDirectory:
    """Trust-the-email directory used until BambooHR is wired up."""

    def get(self, email: str) -> Employee | None:
        if not email:
            return None
        return Employee(email=email)

    def is_active(self, email: str) -> bool:
        return bool(email)
