"""HTTP server for the search-first seat map.

Wraps :class:`office_cli.seats.SeatService` and the floor topology in a
small FastAPI app. The package imports cleanly without the ``[web]``
extra installed — ``fastapi`` is only imported inside :func:`build_app`
when the caller actually constructs an app, and ``uvicorn`` is only
imported inside :func:`run_server`.
"""

from __future__ import annotations

from office_cli.server._app import build_app
from office_cli.server._serve import run_server

__all__ = ["build_app", "run_server"]
