"""Who knows each file, measured by how much of its history they wrote."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable

from ..models import Commit

METRICS = ("lines", "commits")


@dataclass(frozen=True, slots=True)
class FileOwnership:
    path: str
    owner: str
    owner_share: float
    contributors: int
    total_weight: int

    @property
    def is_siloed(self) -> bool:
        """A single person has written this file's entire recorded history."""
        return self.contributors == 1


def file_ownership(commits: Iterable[Commit], *, metric: str = "lines") -> dict[str, FileOwnership]:
    """Find each file's main contributor.

    With ``lines`` a change weighs its added plus deleted lines, with a floor of
    one so binary edits and pure renames still register. With ``commits`` every
    change weighs one. Ties go to the alphabetically first author key, which
    keeps the output stable between runs.
    """
    if metric not in METRICS:
        raise ValueError(f"unknown metric {metric!r}; expected one of {', '.join(METRICS)}")
    weights: dict[str, Counter[str]] = defaultdict(Counter)
    for commit in commits:
        for change in commit.changes:
            weight = 1 if metric == "commits" else max(change.churn, 1)
            weights[change.path][commit.author.key] += weight
    result: dict[str, FileOwnership] = {}
    for path, by_author in weights.items():
        total = sum(by_author.values())
        owner, top = min(by_author.items(), key=lambda item: (-item[1], item[0]))
        result[path] = FileOwnership(path, owner, top / total, len(by_author), total)
    return result


def owner_footprint(ownership: Iterable[FileOwnership]) -> list[tuple[str, int]]:
    """Authors with the number of files they are the main contributor of."""
    counts = Counter(entry.owner for entry in ownership)
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def bus_factor(ownership: Iterable[FileOwnership], *, threshold: float = 0.5) -> int:
    """How few main contributors together cover more than ``threshold`` of the files.

    This is a rough signal rather than a measurement: it says nothing about who
    could actually take a file over. An empty history has a bus factor of zero.
    """
    if not 0 < threshold < 1:
        raise ValueError("threshold must be between 0 and 1")
    entries = list(ownership)
    if not entries:
        return 0
    needed = len(entries) * threshold
    covered = 0
    for count, (_, files) in enumerate(owner_footprint(entries), start=1):
        covered += files
        if covered > needed:
            return count
    return len(owner_footprint(entries))
