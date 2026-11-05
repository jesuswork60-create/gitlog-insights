"""Attribute a file's whole history to its newest name."""

from __future__ import annotations

from typing import Iterable, Iterator

from .models import Commit


class RenameTracker:
    """Rewrites paths to the name each file has at the newest commit seen.

    The tracker relies on commits arriving newest first, which is how ``git log``
    prints them unless told otherwise. A ``--reverse`` log would be attributed
    wrongly.
    """

    def __init__(self) -> None:
        self._latest: dict[str, str] = {}

    def resolve(self, path: str) -> str:
        return self._latest.get(path, path)

    def canonicalize(self, commit: Commit) -> Commit:
        if not self._latest and not any(c.is_rename for c in commit.changes):
            return commit
        # Resolve every row against the state from newer commits first, then
        # record this commit's renames: a commit may swap two names, and updating
        # during the first loop would send both rows to the same file.
        resolved = []
        renames: list[tuple[str, str]] = []
        for change in commit.changes:
            current = self.resolve(change.path)
            if change.is_rename:
                renames.append((change.old_path, current))
            resolved.append(_with_path(change, current))
        for old_path, current in renames:
            self._latest[old_path] = current
        return commit.with_changes(resolved)


def _with_path(change, path):
    if change.path == path:
        return change
    return type(change)(path, change.added, change.deleted, change.old_path)


def follow_renames(commits: Iterable[Commit]) -> Iterator[Commit]:
    tracker = RenameTracker()
    for commit in commits:
        yield tracker.canonicalize(commit)
