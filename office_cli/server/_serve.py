"""Blocking entry point for the FastAPI seat-map server.

Lazy-imports ``uvicorn`` so installs without the ``[web]`` extra still
load the parent package cleanly.
"""

from __future__ import annotations

from typing import Any

from office_cli.cli._errors import EXIT_ENV_ERROR, OfficeError


def run_server(app: Any, *, host: str = "127.0.0.1", port: int = 8000) -> None:
    """Block on ``uvicorn.run(app, host=host, port=port)``.

    Raises :class:`OfficeError` (``EXIT_ENV_ERROR``) when ``uvicorn`` is
    missing so the CLI verb can render a consistent remediation hint.
    """
    try:
        import uvicorn
    except ImportError as err:
        raise OfficeError(
            code=EXIT_ENV_ERROR,
            message="uvicorn is not installed",
            remediation="install the web extra: uv tool install 'office-cli[web]'",
        ) from err
    uvicorn.run(app, host=host, port=port, log_level="info")
