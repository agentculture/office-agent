"""Parser tests for the /whereis slash-command argument."""

from __future__ import annotations

import pytest

from office_cli.slack._resolve import parse_target


def test_empty_text_is_self_lookup() -> None:
    target = parse_target("")
    assert target.self_lookup is True
    assert target.user_id == ""
    assert target.email == ""


def test_whitespace_only_is_self_lookup() -> None:
    assert parse_target("   ").self_lookup is True
    assert parse_target("\t\n").self_lookup is True


def test_mention_with_pipe_name() -> None:
    target = parse_target("<@U12345|alice>")
    assert target.user_id == "U12345"
    assert target.email == ""
    assert target.self_lookup is False


def test_mention_without_pipe_name() -> None:
    target = parse_target("<@U67890>")
    assert target.user_id == "U67890"


def test_mention_takes_precedence_over_email() -> None:
    """A mention buried in text wins even if the text also has an email."""
    target = parse_target("<@U123|alice> alice@x.com")
    assert target.user_id == "U123"
    assert target.email == ""


def test_plain_email() -> None:
    target = parse_target("alice@tipalti.com")
    assert target.email == "alice@tipalti.com"
    assert target.user_id == ""


def test_email_with_surrounding_whitespace() -> None:
    assert parse_target("   alice@tipalti.com   ").email == "alice@tipalti.com"


def test_first_email_wins_among_many() -> None:
    target = parse_target("alice@x.com bob@y.com")
    assert target.email == "alice@x.com"


def test_unparseable_text_marks_failure() -> None:
    target = parse_target("nope")
    assert target.ok is False
    assert target.raw == "nope"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("a@b.io", "a@b.io"),
        ("name+tag@sub.example.co", "name+tag@sub.example.co"),
        ("user.name@x.io", "user.name@x.io"),
        ("a@b.c.d.e.io", "a@b.c.d.e.io"),  # multi-label domain still matches
    ],
)
def test_email_shapes(text: str, expected: str) -> None:
    assert parse_target(text).email == expected


def test_overlong_input_short_circuits() -> None:
    """Inputs over the cap are rejected before any regex runs.

    Defense in depth against ReDoS — even though the email regex is
    constructed to run in linear time, a hard length cap means an
    adversarial input cannot tie up the handler regardless of any
    future regex change.
    """
    huge = "a" * 10_000 + "@" + "b" * 10_000
    target = parse_target(huge)
    assert target.ok is False
    assert target.raw.endswith("…")  # truncated marker


def test_redos_pathological_input_completes_quickly() -> None:
    """Adversarial input that would have been polynomial under the old
    `[A-Za-z0-9.-]+\\.[A-Za-z]{2,}` shape now matches/fails in linear
    time. We do not assert wall-clock — pytest will fail the suite if
    this hangs."""
    import time

    # 200 dot-separated segments with no valid TLD at the end.
    needle = "a@" + ".".join(["b"] * 100) + "."
    start = time.monotonic()
    target = parse_target(needle)
    elapsed = time.monotonic() - start
    # Generous bound — linear-time regex on a 202-char input finishes in
    # microseconds; 1s flags any future regression to a polynomial form.
    assert elapsed < 1.0
    # Last segment is just `.`, so there's no valid TLD; parse should
    # treat the prefix `a@b.b.…b.b` as the match (since `b` qualifies as
    # a 2+-char TLD when paired with the previous `b`). Either matching
    # or failing is acceptable — what matters is that we did not hang.
    assert target.raw == needle.strip()
