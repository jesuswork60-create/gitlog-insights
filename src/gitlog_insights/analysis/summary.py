"""One-screen overview of a history."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from ..models import Commit


@dataclass(frozen=True, slots=True)
class RepoSummary:
    commits: int
    merges: int
    authors: int
    files: int
    added: int
    deleted: int
    first_commit: datetime | None
    last_commit: datetime | None
    median_commit_size: float
    largest_commit: str | None
    largest_commit_size: int

    @property
    def span_days(self) -> int:
        if self.first_commit is None or self.last_commit is None:
            return 0
        return (self.last_commit - self.first_commit).days


def summarize(commits: Sequence[Commit]) -> RepoSummary:
    if not commits:
        return RepoSummary(0, 0, 0, 0, 0, 0, None, None, 0.0, None, 0)
    # Merges carry no numstat rows, so they would drag the median towards zero.
    sizes = [commit.churn for commit in commits if not commit.is_merge]
    largest = max(commits, key=lambda c: (c.churn, c.sha))
    return RepoSummary(
        commits=len(commits),
        merges=sum(1 for c in commits if c.is_merge),
        authors=len({c.author.key for c in commits}),
        files=len({path for c in commits for path in c.paths}),
        added=sum(c.added for c in commits),
        deleted=sum(c.deleted for c in commits),
        first_commit=min(c.authored_at for c in commits),
        last_commit=max(c.authored_at for c in commits),
        median_commit_size=statistics.median(sizes) if sizes else 0.0,
        largest_commit=largest.sha,
        largest_commit_size=largest.churn,
    )
