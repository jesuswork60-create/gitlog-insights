"""Contrast the history before and after a chosen moment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from ..models import Commit
from .authors import author_stats
from .churn import file_stats


@dataclass(frozen=True, slots=True)
class Delta:
    key: str
    before: int
    after: int

    @property
    def change(self) -> int:
        return self.after - self.before


@dataclass(slots=True)
class PeriodComparison:
    split: datetime
    commits_before: int
    commits_after: int
    churn_before: int
    churn_after: int
    files: list[Delta]
    authors: list[Delta]
    new_authors: list[str]
    gone_authors: list[str]


def compare_periods(commits: Iterable[Commit], split: datetime) -> PeriodComparison:
    """Split at ``split``; commits at exactly that moment count as "after"."""
    before: list[Commit] = []
    after: list[Commit] = []
    for commit in commits:
        (after if commit.authored_at >= split else before).append(commit)

    files_before = file_stats(before)
    files_after = file_stats(after)
    file_deltas = [
        Delta(
            path,
            files_before[path].churn if path in files_before else 0,
            files_after[path].churn if path in files_after else 0,
        )
        for path in files_before.keys() | files_after.keys()
    ]
    file_deltas.sort(key=lambda d: (-abs(d.change), d.key))

    authors_before = author_stats(before)
    authors_after = author_stats(after)
    author_deltas = [
        Delta(
            key,
            authors_before[key].commits if key in authors_before else 0,
            authors_after[key].commits if key in authors_after else 0,
        )
        for key in authors_before.keys() | authors_after.keys()
    ]
    author_deltas.sort(key=lambda d: (-abs(d.change), d.key))

    return PeriodComparison(
        split=split,
        commits_before=len(before),
        commits_after=len(after),
        churn_before=sum(c.churn for c in before),
        churn_after=sum(c.churn for c in after),
        files=file_deltas,
        authors=author_deltas,
        new_authors=sorted(authors_after.keys() - authors_before.keys()),
        gone_authors=sorted(authors_before.keys() - authors_after.keys()),
    )
