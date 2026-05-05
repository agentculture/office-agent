"""Unit tests for the pure fuzzy scorer (#39)."""

from __future__ import annotations

import pytest

from office_cli.slack._fuzzy import auto_pick, rank_candidates


def test_exact_match_scores_one() -> None:
    [c] = rank_candidates("alice", [("alice", "alice@example.com")], cutoff=0.0)
    assert c.email == "alice@example.com"
    assert c.score == pytest.approx(1.0)


def test_below_cutoff_is_filtered() -> None:
    """A clearly different label drops out at cutoff=0.7."""
    ranked = rank_candidates("alice", [("zachary", "z@x.com")], cutoff=0.7)
    assert ranked == []


def test_dedup_by_email_keeps_higher_score() -> None:
    """Same email seen via two labels: best score wins, only one row
    survives."""
    ranked = rank_candidates(
        "alice",
        [
            ("Alice Smith", "alice@example.com"),  # weaker fuzzy match
            ("alice", "alice@example.com"),  # exact local-part match
        ],
        cutoff=0.0,
    )
    assert len(ranked) == 1
    assert ranked[0].label == "alice"
    assert ranked[0].score == pytest.approx(1.0)


def test_results_sorted_descending_and_capped() -> None:
    """Three candidates above cutoff, ``limit=2`` keeps the top two
    by score."""
    pool = [
        ("alic", "a@x.com"),  # very close to "alice" (~0.89)
        ("alice", "b@x.com"),  # exact (1.0)
        ("alica", "c@x.com"),  # 0.8
    ]
    ranked = rank_candidates("alice", pool, cutoff=0.7, limit=2)
    assert [c.email for c in ranked] == ["b@x.com", "a@x.com"]


def test_empty_token_returns_empty() -> None:
    assert rank_candidates("", [("alice", "a@x.com")]) == []


def test_blank_label_or_email_skipped() -> None:
    """Defensive: a candidate with an empty label or email is skipped
    silently (no exception)."""
    ranked = rank_candidates(
        "alice",
        [
            ("", "a@x.com"),  # no label
            ("alice", ""),  # no email
            ("alice", "alice@x.com"),  # valid
        ],
        cutoff=0.0,
    )
    assert len(ranked) == 1
    assert ranked[0].email == "alice@x.com"


def test_case_insensitive() -> None:
    ranked = rank_candidates("ALICE", [("Alice", "a@x.com")], cutoff=0.0)
    assert ranked[0].score == pytest.approx(1.0)


def test_auto_pick_single_candidate() -> None:
    [c] = rank_candidates("alice", [("alice", "a@x.com")])
    assert auto_pick([c]) == c


def test_auto_pick_clear_gap_picks_top() -> None:
    pool = [
        ("alice", "alice@x.com"),  # 1.0
        ("alec", "alec@x.com"),  # ~0.5
    ]
    ranked = rank_candidates("alice", pool, cutoff=0.0)
    picked = auto_pick(ranked, gap=0.1)
    assert picked is not None
    assert picked.email == "alice@x.com"


def test_auto_pick_returns_none_within_gap() -> None:
    """Top vs runner-up within the gap → ambiguous; render the
    picker instead of choosing."""
    pool = [
        ("alice", "alice@x.com"),
        ("alica", "alica@x.com"),  # very close fuzzy match
    ]
    ranked = rank_candidates("alice", pool, cutoff=0.0)
    # Force a small gap so this assertion is robust to difflib drift.
    picked = auto_pick(ranked, gap=0.5)
    assert picked is None


def test_auto_pick_empty_returns_none() -> None:
    assert auto_pick([]) is None
