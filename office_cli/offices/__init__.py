"""Office / floor / cluster / room metadata.

The single entry point is :func:`load_offices`, which parses
``<data_dir>/data/offices.yaml`` into immutable dataclasses. Failures raise
:class:`office_cli.cli._errors.OfficeError` so the CLI layer can surface them
without leaking tracebacks.
"""

from __future__ import annotations

from office_cli.offices._models import Cluster, Floor, Office, Room
from office_cli.offices._writer import append_floor_entry
from office_cli.offices._yaml import load_offices

__all__ = ["Cluster", "Floor", "Office", "Room", "append_floor_entry", "load_offices"]
