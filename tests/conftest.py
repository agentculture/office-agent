"""Shared pytest fixtures.

The fixture data dir under ``tests/fixtures/`` provides a self-contained
office topology. The ``data_dir`` fixture copies it (plus an empty
``seats/`` directory) into a tmp path so write-mode tests don't pollute
the repo.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Return a writable copy of the fixture office topology."""
    target = tmp_path / "office-data"
    shutil.copytree(FIXTURES, target)
    (target / "seats").mkdir(exist_ok=True)
    return target


@pytest.fixture
def fixtures_root() -> Path:
    """Read-only path to ``tests/fixtures/``."""
    return FIXTURES
