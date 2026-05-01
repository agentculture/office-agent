"""Role mapping for the v1 seating system (Stage 7, issue #11).

Three roles are recognized:

* :data:`VIEWER` — everyone (default). Sees ``hidden=TRUE`` seats as
  ``"occupied (private)"`` with no email/notes.
* :data:`EDITOR` — HR/IT. Sees full details on hidden seats.
* :data:`PLANNING` — facilities team. Same as editor in v1; the
  draft-SVG and future-dated carve-outs from issue #1 are deferred.

The role for a given email is resolved at view time. The mapping lives
in ``data/offices.yaml`` under a top-level ``roles:`` block, e.g.::

    roles:
      editor: ["hr-it@tipalti.com", "alice@tipalti.com"]
      planning: ["facilities@tipalti.com"]

Anything not listed → ``viewer``. The CLI is operator-only and is
treated as unrestricted (it passes ``role=None`` to the service).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml

from office_cli.cli._errors import EXIT_USER_ERROR, OfficeError

VIEWER = "viewer"
EDITOR = "editor"
PLANNING = "planning"
_ROLES = (VIEWER, EDITOR, PLANNING)
_CONFIGURABLE = (EDITOR, PLANNING)
_SHAPE_HINT = "see docs/architecture.md for the expected shape"


@dataclass(frozen=True)
class RolesConfig:
    """Resolved role-to-emails mapping.

    Both fields hold lowercased emails so lookup is case-insensitive
    without per-call work. ``viewer`` is the default for any email
    that does not appear in either set.
    """

    editor: frozenset[str] = field(default_factory=frozenset)
    planning: frozenset[str] = field(default_factory=frozenset)


def resolve_roles(data_dir: Path) -> RolesConfig:
    """Read the ``roles:`` block from ``data/offices.yaml``.

    Missing block / empty file → empty config (everyone is viewer).
    Malformed shape (e.g. ``editor:`` is a string instead of a list)
    raises :class:`OfficeError(EXIT_USER_ERROR)` with a remediation.
    """
    yaml_path = data_dir / "data" / "offices.yaml"
    if not yaml_path.is_file():
        return RolesConfig()
    with yaml_path.open("r", encoding="utf-8") as f:
        try:
            raw = yaml.safe_load(f) or {}
        except yaml.YAMLError:
            return RolesConfig()
    block = raw.get("roles") or {}
    if not isinstance(block, dict):
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message="roles must be a mapping in offices.yaml",
            remediation=_SHAPE_HINT,
        )
    return RolesConfig(
        editor=_emails(block.get("editor"), key="roles.editor"),
        planning=_emails(block.get("planning"), key="roles.planning"),
    )


def role_for_email(roles: RolesConfig, email: str) -> str:
    """Return the role for ``email``. Defaults to ``viewer``.

    Lookup is case-insensitive — the parsed config already lowercases
    the configured emails; we lowercase the input here.
    """
    if not email:
        return VIEWER
    needle = email.strip().lower()
    if needle in roles.editor:
        return EDITOR
    if needle in roles.planning:
        return PLANNING
    return VIEWER


def is_full_access(role: str | None) -> bool:
    """Return True iff ``role`` sees full details on hidden seats.

    ``role=None`` is the CLI-style unrestricted case. Editor and
    planning both see everything in v1; the planning carve-outs from
    issue #1 (draft SVGs, future-dated visibility) land later.
    """
    return role is None or role in (EDITOR, PLANNING)


def _emails(value: object, *, key: str) -> frozenset[str]:
    """Coerce a YAML list-of-strings into a lowercased frozenset.

    Empty / None → empty set. A non-list value raises
    :class:`OfficeError`.
    """
    if value is None:
        return frozenset()
    if not isinstance(value, list):
        raise OfficeError(
            code=EXIT_USER_ERROR,
            message=f"{key} must be a list of emails",
            remediation=_SHAPE_HINT,
        )
    return frozenset(_normalize(value, key=key))


def _normalize(emails: Iterable[object], *, key: str) -> Iterable[str]:
    for email in emails:
        if not isinstance(email, str):
            raise OfficeError(
                code=EXIT_USER_ERROR,
                message=f"{key} entries must be strings; got {type(email).__name__}",
                remediation=_SHAPE_HINT,
            )
        normalized = email.strip().lower()
        if normalized:
            yield normalized
