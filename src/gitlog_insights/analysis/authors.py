"""Who did what, and over what stretch of time."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Iterable

from ..models import Commit


@dataclass(slots=True)
class AuthorStats:
    key: str
    name: str
    email: str
    commits: int = 0
    merges: int = 0
    added: int = 0
    deleted: int = 0
    files: set[str] = field(default_factory=set)
    active_days: set[date] = field(default_factory=set)
    first_commit: datetime | None = None
    last_commit: datetime | None = None

    @property
    def churn(self) -> int:
        return self.added + self.deleted

    @property
    def longest_streak(self) -> int:
        """Longest run of consecutive days with at least one commit."""
        best = run = 0
        previous: date | None = None
        for day in sorted(self.active_days):
            run = run + 1 if previous and day - previous == timedelta(days=1) else 1
            best = max(best, run)
            previous = day
        return best


def author_stats(commits: Iterable[Commit]) -> dict[str, AuthorStats]:
    """Group by :attr:`Author.key`.

    The displayed name is the one on the author's newest commit, so a corrected
    spelling wins over old ones whichever order the commits come in. Active days
    are counted in the author's own recorded time zone: a commit at 23:30 local
    time belongs to that local day.
    """
    stats: dict[str, AuthorStats] = {}
    for commit in commits:
        key = commit.author.key
        entry = stats.get(key)
        if entry is None:
            entry = stats[key] = AuthorStats(key, commit.author.name, commit.author.email)
        entry.commits += 1
        entry.merges += 1 if commit.is_merge else 0
        entry.added += commit.added
        entry.deleted += commit.deleted
        entry.files.update(commit.paths)
        when = commit.authored_at
        entry.active_days.add(when.date())
        if entry.first_commit is None or when < entry.first_commit:
            entry.first_commit = when
        if entry.last_commit is None or when > entry.last_commit:
            entry.last_commit = when
            entry.name = commit.author.name
            entry.email = commit.author.email
    return stats


def rank_authors(
    stats: Iterable[AuthorStats], *, by: str = "commits", limit: int | None = None
) -> list[AuthorStats]:
    metrics = {
        "commits": lambda s: s.commits,
        "churn": lambda s: s.churn,
        "files": lambda s: len(s.files),
        "days": lambda s: len(s.active_days),
    }
    if by not in metrics:
        raise ValueError(f"unknown sort key {by!r}; expected one of {', '.join(metrics)}")
    metric = metrics[by]
    ranked = sorted(stats, key=lambda s: (-metric(s), s.key))
    return ranked if limit is None else ranked[:limit]
