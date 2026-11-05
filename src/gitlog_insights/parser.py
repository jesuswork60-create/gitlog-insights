"""Stream parser for ``git log --numstat`` output.

Two layouts are understood and may even be mixed in one stream:

* the machine layout produced by :data:`LOG_FORMAT`, where each commit header is
  a single line of ``\\x1f``-separated fields introduced by ``\\x1e``;
* git's default human layout (``commit <sha>``, ``Author:``, ``Date:``, an
  indented message), so a saved ``git log --numstat > file`` works too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Iterator

from .dates import parse_git_date
from .models import Author, Commit, FileChange
from .numstat import parse_numstat

RECORD_SEP = "\x1e"
FIELD_SEP = "\x1f"
LOG_FORMAT = "%x1e%H%x1f%P%x1f%an%x1f%ae%x1f%aI%x1f%s"

_COMMIT_LINE = re.compile(r"^commit ([0-9a-f]{7,64})((?: [0-9a-f]{7,64})*)(?: \(.*\))?$")
_AUTHOR = re.compile(r"^(.*?)\s*<([^<>]*)>\s*$")
_HEADER_KEY = re.compile(r"^([A-Za-z]+):\s*(.*)$")


class LogParseError(ValueError):
    """Raised in strict mode; carries the 1-based line number of the problem."""

    def __init__(self, line_number: int, message: str) -> None:
        super().__init__(f"line {line_number}: {message}")
        self.line_number = line_number


@dataclass(slots=True)
class _Draft:
    """A commit under construction; only the default layout builds it in steps."""

    sha: str
    line_number: int
    parents: tuple[str, ...] = ()
    author: Author | None = None
    authored_at: datetime | None = None
    subject: str | None = None
    changes: list[FileChange] = field(default_factory=list)
    in_headers: bool = False


def parse_author(text: str) -> Author:
    """Split ``Name <email>``; text without angle brackets is taken as the name."""
    match = _AUTHOR.match(text.strip())
    if match:
        return Author(match.group(1).strip(), match.group(2).strip())
    return Author(text.strip(), "")


class LogParser:
    """Turns lines into :class:`Commit` objects, one commit at a time.

    In lenient mode (the default) unrecognised lines and incomplete commits are
    counted in :attr:`skipped_lines` and :attr:`skipped_commits`; in strict mode
    they raise :class:`LogParseError`.
    """

    def __init__(self, *, strict: bool = False) -> None:
        self.strict = strict
        self.skipped_lines = 0
        self.skipped_commits = 0
        self.commits_parsed = 0
        self._line_number = 0

    def parse(self, lines: Iterable[str]) -> Iterator[Commit]:
        draft: _Draft | None = None
        for raw in lines:
            self._line_number += 1
            line = raw.rstrip("\r\n")
            header = self._start_of_commit(line)
            if header is not None:
                if draft is not None:
                    finished = self._finish(draft)
                    if finished is not None:
                        yield finished
                draft = header
            elif draft is None:
                if line.strip():
                    self._reject(f"text before the first commit: {line[:60]!r}")
            else:
                self._feed(draft, line)
        if draft is not None:
            finished = self._finish(draft)
            if finished is not None:
                yield finished

    def _start_of_commit(self, line: str) -> _Draft | None:
        if line.startswith(RECORD_SEP):
            return self._machine_header(line)
        match = _COMMIT_LINE.match(line)
        if match:
            parents = tuple(match.group(2).split())
            return _Draft(match.group(1), self._line_number, parents=parents, in_headers=True)
        return None

    def _machine_header(self, line: str) -> _Draft:
        parts = line[len(RECORD_SEP) :].split(FIELD_SEP)
        if len(parts) != 6:
            draft = _Draft(parts[0] or "?", self._line_number)
            self._reject(f"expected 6 header fields, found {len(parts)}")
            return draft
        sha, parents, name, email, when, subject = parts
        draft = _Draft(sha, self._line_number, parents=tuple(parents.split()))
        draft.author = Author(name, email)
        draft.subject = subject
        try:
            draft.authored_at = parse_git_date(when)
        except ValueError:
            self._reject(f"unreadable date {when!r}")
        return draft

    def _feed(self, draft: _Draft, line: str) -> None:
        if draft.in_headers:
            self._feed_header(draft, line)
            return
        if line.startswith("    "):
            # The first indented line is the subject; the rest is the message body.
            if draft.subject is None:
                draft.subject = line.strip()
            return
        if not line.strip():
            return
        change = parse_numstat(line)
        if change is None:
            self._reject(f"not a numstat row: {line[:60]!r}")
        else:
            draft.changes.append(change)

    def _feed_header(self, draft: _Draft, line: str) -> None:
        if not line.strip():
            draft.in_headers = False
            return
        match = _HEADER_KEY.match(line)
        if not match:
            self._reject(f"malformed header: {line[:60]!r}")
            return
        key, value = match.groups()
        if key == "Author":
            draft.author = parse_author(value)
        elif key in ("Date", "AuthorDate"):
            try:
                draft.authored_at = parse_git_date(value)
            except ValueError:
                self._reject(f"unreadable date {value!r}")
        elif key == "Merge" and not draft.parents:
            draft.parents = tuple(value.split())
        # Commit:, CommitDate: and Reflog headers carry nothing we report on.

    def _finish(self, draft: _Draft) -> Commit | None:
        if draft.author is None or draft.authored_at is None:
            self.skipped_commits += 1
            if self.strict:
                raise LogParseError(
                    draft.line_number, f"commit {draft.sha} has no author or date"
                )
            return None
        self.commits_parsed += 1
        return Commit(
            sha=draft.sha,
            author=draft.author,
            authored_at=draft.authored_at,
            subject=draft.subject or "",
            changes=draft.changes,
            parents=draft.parents,
        )

    def _reject(self, message: str) -> None:
        self.skipped_lines += 1
        if self.strict:
            raise LogParseError(self._line_number, message)


def parse_log(lines: Iterable[str], *, strict: bool = False) -> Iterator[Commit]:
    """Convenience wrapper for callers that do not need the skip counters."""
    return LogParser(strict=strict).parse(lines)
