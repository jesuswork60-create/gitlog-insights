"""Restrict a commit stream by date, author and path."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from fnmatch import fnmatchcase
from typing import Iterable, Iterator

from .models import Commit


def match_path(path: str, pattern: str) -> bool:
    """Match a repository path against one pattern, loosely like ``.gitignore``.

    ``docs/`` matches everything under ``docs``; a pattern without a slash is
    tried against the file name at any depth (``*.lock``); other patterns must
    match the whole path or one of its leading directories.
    """
    if pattern.endswith("/"):
        return path.startswith(pattern)
    if "/" not in pattern and fnmatchcase(path.rsplit("/", 1)[-1], pattern):
        return True
    if fnmatchcase(path, pattern):
        return True
    return path.startswith(pattern + "/")


@dataclass(frozen=True, slots=True)
class CommitFilter:
    since: datetime | None = None
    until: datetime | None = None
    authors: tuple[str, ...] = ()
    exclude_authors: tuple[str, ...] = ()
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    include_merges: bool = True

    def keeps_path(self, path: str) -> bool:
        if any(match_path(path, pattern) for pattern in self.exclude):
            return False
        if not self.include:
            return True
        return any(match_path(path, pattern) for pattern in self.include)

    def keeps_author(self, commit: Commit) -> bool:
        haystack = f"{commit.author.name} {commit.author.email}".lower()
        if any(needle.lower() in haystack for needle in self.exclude_authors):
            return False
        if not self.authors:
            return True
        return any(needle.lower() in haystack for needle in self.authors)

    def keeps_date(self, commit: Commit) -> bool:
        if self.since is not None and commit.authored_at < self.since:
            return False
        if self.until is not None and commit.authored_at > self.until:
            return False
        return True

    def apply(self, commits: Iterable[Commit]) -> Iterator[Commit]:
        """Yield matching commits, with their file lists narrowed by the path rules.

        A commit whose every file is filtered away is dropped, unless no path
        rule is active: empty commits and merges survive when only dates and
        authors are being filtered.
        """
        path_rules = bool(self.include or self.exclude)
        for commit in commits:
            if commit.is_merge and not self.include_merges:
                continue
            if not self.keeps_date(commit) or not self.keeps_author(commit):
                continue
            if path_rules:
                kept = [c for c in commit.changes if self.keeps_path(c.path)]
                if not kept:
                    continue
                if len(kept) != len(commit.changes):
                    commit = commit.with_changes(kept)
            yield commit
