"""Per-file and per-directory change statistics."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from ..models import Commit

SORT_KEYS = ("churn", "commits", "authors", "added", "deleted", "path")


@dataclass(slots=True)
class FileStats:
    path: str
    commits: int = 0
    added: int = 0
    deleted: int = 0
    binary_changes: int = 0
    authors: set[str] = field(default_factory=set)
    first_changed: datetime | None = None
    last_changed: datetime | None = None

    @property
    def churn(self) -> int:
        return self.added + self.deleted

    def record(self, commit: Commit, added: int | None, deleted: int | None) -> None:
        self.commits += 1
        if added is None or deleted is None:
            self.binary_changes += 1
        else:
            self.added += added
            self.deleted += deleted
        self.authors.add(commit.author.key)
        when = commit.authored_at
        if self.first_changed is None or when < self.first_changed:
            self.first_changed = when
        if self.last_changed is None or when > self.last_changed:
            self.last_changed = when


def file_stats(commits: Iterable[Commit]) -> dict[str, FileStats]:
    stats: dict[str, FileStats] = {}
    for commit in commits:
        for change in commit.changes:
            entry = stats.get(change.path)
            if entry is None:
                entry = stats[change.path] = FileStats(change.path)
            entry.record(commit, change.added, change.deleted)
    return stats


def rank_files(
    stats: Iterable[FileStats], *, by: str = "churn", limit: int | None = None
) -> list[FileStats]:
    """Order files by a metric, largest first, breaking ties by path."""
    if by not in SORT_KEYS:
        raise ValueError(f"unknown sort key {by!r}; expected one of {', '.join(SORT_KEYS)}")
    if by == "path":
        ranked = sorted(stats, key=lambda s: s.path)
    elif by == "authors":
        ranked = sorted(stats, key=lambda s: (-len(s.authors), s.path))
    else:
        ranked = sorted(stats, key=lambda s: (-getattr(s, by), s.path))
    return ranked if limit is None else ranked[:limit]


def directory_of(path: str, depth: int) -> str:
    """The first ``depth`` directory levels of a path; top-level files map to ``.``."""
    parts = path.split("/")[:-1]
    return "/".join(parts[:depth]) if parts else "."


def directory_stats(commits: Iterable[Commit], *, depth: int = 1) -> dict[str, FileStats]:
    """Roll changes up to directories. A commit counts once per directory it touches."""
    if depth < 1:
        raise ValueError("depth must be at least 1")
    stats: dict[str, FileStats] = {}
    for commit in commits:
        totals: dict[str, list[int]] = {}
        for change in commit.changes:
            directory = directory_of(change.path, depth)
            bucket = totals.setdefault(directory, [0, 0])
            bucket[0] += change.added or 0
            bucket[1] += change.deleted or 0
        for directory, (added, deleted) in totals.items():
            entry = stats.get(directory)
            if entry is None:
                entry = stats[directory] = FileStats(directory)
            entry.record(commit, added, deleted)
    return stats
