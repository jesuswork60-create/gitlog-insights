"""Files that tend to change in the same commit."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from typing import Iterable

from ..models import Commit


@dataclass(frozen=True, slots=True)
class CoChangePair:
    """``a`` sorts before ``b``; ``support`` is the number of shared commits."""

    a: str
    b: str
    support: int
    a_commits: int
    b_commits: int

    @property
    def coupling(self) -> float:
        """Jaccard index: shared commits over commits touching either file."""
        return self.support / (self.a_commits + self.b_commits - self.support)

    @property
    def confidence_a_to_b(self) -> float:
        """How often a change to ``a`` also changed ``b``."""
        return self.support / self.a_commits

    @property
    def confidence_b_to_a(self) -> float:
        return self.support / self.b_commits


def cochange_pairs(
    commits: Iterable[Commit],
    *,
    min_support: int = 2,
    max_files: int = 30,
    min_coupling: float = 0.0,
    limit: int | None = None,
) -> list[CoChangePair]:
    """Rank file pairs by shared commits, then by coupling.

    Commits touching more than ``max_files`` files are left out entirely, both
    from pairs and from per-file totals. Mass reformatting and vendored updates
    would otherwise couple everything to everything, and they are also where the
    pair count grows quadratically.
    """
    pair_counts: Counter[tuple[str, str]] = Counter()
    file_counts: Counter[str] = Counter()
    for commit in commits:
        paths = sorted(set(commit.paths))
        if len(paths) > max_files:
            continue
        file_counts.update(paths)
        pair_counts.update(combinations(paths, 2))
    pairs = [
        CoChangePair(a, b, support, file_counts[a], file_counts[b])
        for (a, b), support in pair_counts.items()
        if support >= min_support
    ]
    if min_coupling > 0:
        pairs = [pair for pair in pairs if pair.coupling >= min_coupling]
    pairs.sort(key=lambda p: (-p.support, -p.coupling, p.a, p.b))
    return pairs if limit is None else pairs[:limit]


def partners_of(path: str, pairs: Iterable[CoChangePair]) -> list[tuple[str, CoChangePair]]:
    """Files coupled to ``path``, strongest first, given already computed pairs."""
    found = [
        (pair.b if pair.a == path else pair.a, pair)
        for pair in pairs
        if path in (pair.a, pair.b)
    ]
    found.sort(key=lambda item: (-item[1].coupling, item[0]))
    return found
