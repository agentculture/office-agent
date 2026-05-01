"""Entry point for ``python -m office_cli``."""

from __future__ import annotations

import sys

from office_cli.cli import main

if __name__ == "__main__":
    sys.exit(main())
