"""Activity over the calendar: per-period totals and a weekly rhythm grid."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from ..dates import bucket_key, iter_bucket_keys
from ..models import Commit

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass(slots=True)
class Bucket:
    key: str
    commits: int = 0
    added: int = 0
    deleted: int = 0
    authors: set[str] = field(default_factory=set)


def timeline(
    commits: Sequence[Commit], *, period: str = "month", fill_gaps: bool = True
) -> list[Bucket]:
    """Totals per calendar period in UTC, oldest first.

    With ``fill_gaps`` quiet periods appear as zero rows, so a chart of the output
    shows the pause instead of hiding it.
    """
    buckets: dict[str, Bucket] = {}
    for commit in commits:
        key = bucket_key(commit.authored_at, period)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = buckets[key] = Bucket(key)
        bucket.commits += 1
        bucket.added += commit.added
        bucket.deleted += commit.deleted
        bucket.authors.add(commit.author.key)
    if not buckets:
        return []
    if fill_gaps:
        first = min(commit.authored_at for commit in commits)
        last = max(commit.authored_at for commit in commits)
        return [buckets.get(key) or Bucket(key) for key in iter_bucket_keys(first, last, period)]
    return [buckets[key] for key in sorted(buckets)]


def rhythm(commits: Iterable[Commit]) -> list[list[int]]:
    """A 7x24 grid of commit counts, Monday first, in each author's local time."""
    grid = [[0] * 24 for _ in WEEKDAYS]
    for commit in commits:
        when = commit.authored_at
        grid[when.weekday()][when.hour] += 1
    return grid
