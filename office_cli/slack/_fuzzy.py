"""Pure fuzzy scoring for ``/whereis`` partial-name resolution (#39).

The third tier of the resolution chain after the exact local-part path
(#29) and exact Slack-name path (#38). The scorer is intentionally
small and dependency-free: stdlib :mod:`difflib` is enough at v1
scale, and keeping the function pure makes it cheap to test
deterministically.

This module never imports the Slack SDK or touches a network. Callers
hand it a `(label, email)` iterable and read back ranked
:class:`FuzzyCandidate` results.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable

DEFAULT_CUTOFF = 0.7
DEFAULT_LIMIT = 5
DEFAULT_AUTO_PICK_GAP = 0.05


@dataclass(frozen=True)
class FuzzyCandidate:
    """One ranked hit. ``email`` is the resolution target;
    ``label`` is what to render in the UI; ``score`` is the
    :class:`difflib.SequenceMatcher` ratio against the search token
    (0.0–1.0, higher is better)."""

    email: str
    label: str
    score: float


def rank_candidates(
    token: str,
    candidates: Iterable[tuple[str, str]],
    *,
    cutoff: float = DEFAULT_CUTOFF,
    limit: int = DEFAULT_LIMIT,
) -> list[FuzzyCandidate]:
    """Score every ``(label, email)`` against ``token`` (case-
    insensitive), drop everything below ``cutoff``, dedupe by email
    keeping the highest-scoring label, sort by score desc, and cap at
    ``limit``.

    Dedup is critical: the same person frequently appears via both
    the assignment-store local-part path and the Slack roster, and we
    don't want them rendered twice or competing for the auto-pick
    gap. When two labels tie on score, the one encountered first
    wins (callers control order — local-parts before roster names is
    the convention).
    """
    if not token:
        return []
    needle = token.lower()
    best: dict[str, FuzzyCandidate] = {}
    for label, email in candidates:
        if not email or not label:
            continue
        score = SequenceMatcher(None, needle, label.lower()).ratio()
        if score < cutoff:
            continue
        existing = best.get(email)
        if existing is None or score > existing.score:
            best[email] = FuzzyCandidate(email=email, label=label, score=score)
    ranked = sorted(best.values(), key=lambda c: c.score, reverse=True)
    return ranked[:limit]


def auto_pick(
    candidates: list[FuzzyCandidate],
    *,
    gap: float = DEFAULT_AUTO_PICK_GAP,
) -> FuzzyCandidate | None:
    """Decide whether the top candidate is unambiguously the best.

    Returns the top :class:`FuzzyCandidate` iff exactly one candidate
    cleared the cutoff, or the top score exceeds the runner-up by at
    least ``gap``. Otherwise ``None`` — the caller should render an
    interactive disambiguation list.

    The "wrong auto-pick" cost is high (publicly mis-naming someone
    in a Slack channel), so the gap defaults to a conservative 0.05
    — about three SequenceMatcher edits' worth of confidence.
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    if candidates[0].score - candidates[1].score >= gap:
        return candidates[0]
    return None
