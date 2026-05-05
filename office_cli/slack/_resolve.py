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

ReDoS safety
------------
Slack caps slash-command text at ~3000 characters; we further reject
input over :data:`_MAX_INPUT_LEN` (256) before any regex runs. The
email regex is split into a literal-dot-separated label structure
(``[A-Za-z0-9-]+`` segments + ``\\.`` separators) so the character
classes do not overlap with the dot — eliminating the polynomial
backtracking the original ``[A-Za-z0-9.-]+\\.[A-Za-z]{2,}`` form
exhibited on adversarial inputs like ``a@b.b.b.b…`` without a valid
TLD.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_MAX_INPUT_LEN = 256
_MENTION_RE = re.compile(r"<@(?P<user_id>[UW][A-Z0-9]+)(?:\|[^>]*)?>")
# Domain labels intentionally exclude `.` so the literal `\.` separators
# are unambiguous — no overlapping classes, no super-linear backtracking.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
# Trailing ``YYYY-MM-DD`` token. Anchored to a word boundary at the end
# of the string so we only peel the date when it is the last token; an
# email or mention preceding it stays intact.
_TRAILING_DATE_RE = re.compile(r"(?:^|\s)(?P<date>\d{4}-\d{2}-\d{2})\s*$")


@dataclass(frozen=True)
class ParsedTarget:
    """Result of parsing the slash-command text.

    Exactly one of ``user_id`` / ``email`` / ``bare_token`` is set when
    the parse succeeds; all are empty when the text was not parseable.
    ``self_lookup`` flags the no-arg case so the caller can read the
    invoker's own ``user_id`` from the command body. ``as_of`` is the
    optional trailing ``YYYY-MM-DD`` token (Stage 6); empty when the
    caller did not pass a date. ``bare_token`` (#29 MVP) carries the
    name-or-username form (``alice``, ``ori.nachum``, ``@ori.nachum``)
    for the caller to resolve via the assignment store's email
    local-parts.
    """

    user_id: str = ""
    email: str = ""
    self_lookup: bool = False
    raw: str = ""
    as_of: str = ""
    bare_token: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.user_id or self.email or self.self_lookup or self.bare_token)


def parse_target(text: str) -> ParsedTarget:
    """Parse the text after ``/whereis`` into a :class:`ParsedTarget`.

    Mention parsing happens *before* email parsing so a "user with
    `<@U123>` profile email" mention does not slip through as plain
    text. Whitespace-only / empty text → ``self_lookup``. A trailing
    ``YYYY-MM-DD`` token is peeled before mention/email parsing so
    ``/whereis alice@x 2026-07-01`` and ``/whereis 2026-07-01`` both
    work. Input over :data:`_MAX_INPUT_LEN` short-circuits to a parse
    failure with the raw input truncated for the response message —
    defense in depth against runaway regex evaluation, even though both
    regexes are constructed to run in linear time.
    """
    raw = text or ""
    if len(raw) > _MAX_INPUT_LEN:
        return ParsedTarget(raw=raw[:_MAX_INPUT_LEN] + "…")
    stripped = raw.strip()
    if not stripped:
        return ParsedTarget(self_lookup=True, raw="")

    as_of = ""
    date_match = _TRAILING_DATE_RE.search(stripped)
    if date_match:
        as_of = date_match["date"]
        stripped = stripped[: date_match.start()].strip()
        if not stripped:
            return ParsedTarget(self_lookup=True, raw=raw.strip(), as_of=as_of)

    mention = _MENTION_RE.search(stripped)
    if mention:
        return ParsedTarget(user_id=mention["user_id"], raw=raw.strip(), as_of=as_of)

    email = _EMAIL_RE.search(stripped)
    if email:
        return ParsedTarget(email=email.group(0), raw=raw.strip(), as_of=as_of)

    # #29 MVP: accept a bare name / username token as a hint for the
    # caller to resolve against the assignment store's email local-
    # parts. Strip a single leading ``@`` (failed-autocomplete case),
    # then take the first whitespace-separated token. Tokens that still
    # contain an ``@`` after stripping aren't valid bare names — let
    # the parse fail rather than feeding a broken email downstream.
    first = stripped.split()[0]
    if first.startswith("@"):
        first = first[1:]
    if first and "@" not in first:
        return ParsedTarget(bare_token=first, raw=raw.strip(), as_of=as_of)

    return ParsedTarget(raw=raw.strip(), as_of=as_of)
