"""``office serve`` — run the FastAPI seat-map HTTP server.

Blocks on ``uvicorn.run``. Configuration is env-first / flag override
so operators can drop the verb into a systemd / docker entry point.
"""

from __future__ import annotations

import argparse

from office_cli._config import add_data_dir_arg, resolve_data_dir
from office_cli.cli._errors import EXIT_ENV_ERROR, OfficeError
from office_cli.cli._output import emit_diagnostic
from office_cli.seats import build_service


def cmd_serve(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args)
    service = build_service(data_dir, actor="web")

    try:
        from office_cli.server import build_app, run_server
    except ImportError as err:  # pragma: no cover — guarded by build_app
        raise OfficeError(
            code=EXIT_ENV_ERROR,
            message="server backend is not installed",
            remediation="install the web extra: pip install office-cli[web]",
        ) from err

    app = build_app(service, data_dir=data_dir)
    emit_diagnostic(f"office serve listening on http://{args.host}:{args.port}")
    run_server(app, host=args.host, port=args.port)
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "serve",
        help="Run the FastAPI seat-map server.",
        description=(
            "Blocking FastAPI / Uvicorn HTTP server for the search-first "
            "seat map. Requires the [web] extra "
            "(pip install office-cli[web])."
        ),
    )
    p.add_argument(
        "--host",
        default="127.0.0.1",
        help="Interface to bind. Default 127.0.0.1 (loopback).",
    )
    p.add_argument(
        "--port",
        type=int,
        default=8000,
        help="TCP port. Default 8000. Pass 0 to let the OS pick.",
    )
    add_data_dir_arg(p)
    p.set_defaults(func=cmd_serve)
