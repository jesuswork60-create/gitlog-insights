"""Plain records shared by the parser and every analysis."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Iterable


@dataclass(frozen=True, slots=True)
class Author:
    name: str
    email: str

    @property
    def key(self) -> str:
        """Stable identity used for grouping; emails compare case-insensitively."""
        return self.email.lower() if self.email else self.name.lower()

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>" if self.email else self.name


@dataclass(frozen=True, slots=True)
class FileChange:
    """One numstat row. ``added``/``deleted`` are ``None`` for binary files."""

    path: str
    added: int | None = 0
    deleted: int | None = 0
    old_path: str | None = None

    @property
    def is_binary(self) -> bool:
        return self.added is None or self.deleted is None

    @property
    def is_rename(self) -> bool:
        return self.old_path is not None and self.old_path != self.path

    @property
    def churn(self) -> int:
        return (self.added or 0) + (self.deleted or 0)


@dataclass(slots=True)
class Commit:
    sha: str
    author: Author
    authored_at: datetime
    subject: str = ""
    changes: list[FileChange] = field(default_factory=list)
    parents: tuple[str, ...] = ()

    @property
    def is_merge(self) -> bool:
        return len(self.parents) > 1

    @property
    def added(self) -> int:
        return sum(c.added or 0 for c in self.changes)

    @property
    def deleted(self) -> int:
        return sum(c.deleted or 0 for c in self.changes)

    @property
    def churn(self) -> int:
        return self.added + self.deleted

    @property
    def paths(self) -> list[str]:
        return [c.path for c in self.changes]

    def with_changes(self, changes: Iterable[FileChange]) -> "Commit":
        return replace(self, changes=list(changes))

    def with_author(self, author: Author) -> "Commit":
        return replace(self, author=author)
