"""Explain catalog resolver — markdown keyed by command-path tuples (stable-contract)."""

from __future__ import annotations

from office_cli.cli._errors import EXIT_USER_ERROR, OfficeError
from office_cli.explain.catalog import ENTRIES


def resolve(path: tuple[str, ...]) -> str:
    if path in ENTRIES:
        return ENTRIES[path]
    display = " ".join(path) if path else "<root>"
    raise OfficeError(
        code=EXIT_USER_ERROR,
        message=f"no explain entry for: {display}",
        remediation="list known entries with: office explain office",
    )


def known_paths() -> list[tuple[str, ...]]:
    return list(ENTRIES.keys())
