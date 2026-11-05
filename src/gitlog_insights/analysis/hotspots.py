"""Files where recent, repeated change concentrates."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Sequence

from ..models import Commit


@dataclass(frozen=True, slots=True)
class Hotspot:
    path: str
    score: float
    commits: int
    churn: int
    authors: int
    last_changed: datetime


def hotspots(
    commits: Sequence[Commit],
    *,
    half_life_days: float = 90.0,
    reference: datetime | None = None,
    limit: int | None = None,
) -> list[Hotspot]:
    """Score files by recency-weighted activity.

    Every touch adds ``(1 + log2(1 + lines)) * 0.5 ** (age / half_life)``. The log
    keeps a single huge commit from outranking steady editing, and the decay makes
    old activity fade. Age is measured from ``reference``, which defaults to the
    newest commit in the data rather than today, so a report on a saved log gives
    the same answer whenever it is run.
    """
    if half_life_days <= 0:
        raise ValueError("half_life_days must be positive")
    if not commits:
        return []
    anchor = reference or max(commit.authored_at for commit in commits)
    scores: dict[str, float] = {}
    touches: dict[str, int] = {}
    churn: dict[str, int] = {}
    authors: dict[str, set[str]] = {}
    latest: dict[str, datetime] = {}
    for commit in commits:
        age_days = max((anchor - commit.authored_at).total_seconds() / 86400.0, 0.0)
        decay = 0.5 ** (age_days / half_life_days)
        for change in commit.changes:
            path = change.path
            weight = 1.0 + math.log2(1 + change.churn)
            scores[path] = scores.get(path, 0.0) + weight * decay
            touches[path] = touches.get(path, 0) + 1
            churn[path] = churn.get(path, 0) + change.churn
            authors.setdefault(path, set()).add(commit.author.key)
            if path not in latest or commit.authored_at > latest[path]:
                latest[path] = commit.authored_at
    ranked = [
        Hotspot(path, score, touches[path], churn[path], len(authors[path]), latest[path])
        for path, score in scores.items()
    ]
    ranked.sort(key=lambda h: (-h.score, h.path))
    return ranked if limit is None else ranked[:limit]
