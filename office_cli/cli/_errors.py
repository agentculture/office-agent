"""OfficeError and exit-code policy (stable-contract from afi-cli).

Every failure inside office raises :class:`OfficeError`. The CLI entry
point catches it and exits with :attr:`OfficeError.code`. Guarantees:

* no Python traceback leaks to stderr;
* every error has shape ``{code, message, remediation}``;
* the exit-code policy is centralised.
"""

from __future__ import annotations

from dataclasses import dataclass

# Exit-code policy (documented in ``office learn`` output).
# 0  = success
# 1  = user-input error (bad flag, bad path, missing arg)
# 2  = environment / setup error
# 3  = internal error (unexpected exception not classified above)
# 4+ = reserved
EXIT_SUCCESS = 0
EXIT_USER_ERROR = 1
EXIT_ENV_ERROR = 2
EXIT_INTERNAL_ERROR = 3


@dataclass
class OfficeError(Exception):
    """Structured error with a remediation hint for agents."""

    code: int
    message: str
    remediation: str = ""

    def __post_init__(self) -> None:
        super().__init__(self.message)

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "remediation": self.remediation,
        }
