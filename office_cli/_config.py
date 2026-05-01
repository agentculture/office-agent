"""Resolve where the office data (offices.yaml, floors/, seats/) lives.

Resolution order:

1. ``--data-dir`` CLI flag (passed through ``args.data_dir``);
2. ``OFFICE_DATA_DIR`` environment variable;
3. the current working directory.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from office_cli.cli._errors import EXIT_ENV_ERROR, OfficeError


def resolve_data_dir(args: argparse.Namespace | None = None) -> Path:
    explicit = getattr(args, "data_dir", None) if args is not None else None
    candidate: Path
    if explicit:
        candidate = Path(explicit).expanduser()
    elif os.environ.get("OFFICE_DATA_DIR"):
        candidate = Path(os.environ["OFFICE_DATA_DIR"]).expanduser()
    else:
        candidate = Path.cwd()
    if not candidate.is_dir():
        raise OfficeError(
            code=EXIT_ENV_ERROR,
            message=f"data dir does not exist: {candidate}",
            remediation="pass --data-dir or set OFFICE_DATA_DIR to the office-agent checkout",
        )
    return candidate


def add_data_dir_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--data-dir",
        help="Directory containing data/offices.yaml, floors/, seats/. "
        "Defaults to $OFFICE_DATA_DIR or the current working directory.",
    )


def assignments_csv(data_dir: Path) -> Path:
    return data_dir / "seats" / "assignments.csv"


def audit_log_csv(data_dir: Path) -> Path:
    return data_dir / "seats" / "audit-log.csv"
