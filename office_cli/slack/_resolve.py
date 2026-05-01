"""Pure parsers for the ``/whereis`` slash-command argument.

The Slack listener handles three input shapes:

* empty text → caller asks about their own seat (``user_id`` from the
  command body, resolved via ``users.info``);
* ``<@U123|alice>`` mention → Slack-encoded user reference; we extract
  the user id and resolve via ``users.info``;
* plain text containing an email — used directly.

This module is pure: it does not import the Slack SDK and never makes
network calls. All resolution that needs ``users.info`` is done by the
caller using the parsed user id.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_MENTION_RE = re.compile(r"<@(?P<user_id>[UW][A-Z0-9]+)(?:\|[^>]*)?>")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


@dataclass(frozen=True)
class ParsedTarget:
    """Result of parsing the slash-command text.

    Exactly one of ``user_id`` / ``email`` is set when the parse succeeds;
    both are empty when the text was not parseable. ``self_lookup`` flags
    the no-arg case so the caller can read the invoker's own ``user_id``
    from the command body.
    """

    user_id: str = ""
    email: str = ""
    self_lookup: bool = False
    raw: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.user_id or self.email or self.self_lookup)


def parse_target(text: str) -> ParsedTarget:
    """Parse the text after ``/whereis`` into a :class:`ParsedTarget`.

    Mention parsing happens *before* email parsing so a "user with
    `<@U123>` profile email" mention does not slip through as plain
    text. Whitespace-only / empty text → ``self_lookup``.
    """
    stripped = (text or "").strip()
    if not stripped:
        return ParsedTarget(self_lookup=True, raw="")

    mention = _MENTION_RE.search(stripped)
    if mention:
        return ParsedTarget(user_id=mention["user_id"], raw=stripped)

    email = _EMAIL_RE.search(stripped)
    if email:
        return ParsedTarget(email=email.group(0), raw=stripped)

    return ParsedTarget(raw=stripped)
