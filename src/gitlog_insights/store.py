"""Save parsed history to a JSON Lines snapshot and read it back.

A snapshot lets reports run without the repository, and without running git
again on a large history. The first line is a small header naming the format
version; each following line is one commit.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import IO, Iterable, Iterator

from .models import Author, Commit, FileChange

FORMAT_NAME = "gitlog-insights-snapshot"
FORMAT_VERSION = 1


class SnapshotError(ValueError):
    pass


def commit_to_dict(commit: Commit) -> dict:
    return {
        "sha": commit.sha,
        "parents": list(commit.parents),
        "author": commit.author.name,
        "email": commit.author.email,
        "at": commit.authored_at.isoformat(),
        "subject": commit.subject,
        "changes": [
            [change.path, change.added, change.deleted, change.old_path]
            for change in commit.changes
        ],
    }


def commit_from_dict(data: dict) -> Commit:
    return Commit(
        sha=data["sha"],
        author=Author(data["author"], data["email"]),
        authored_at=datetime.fromisoformat(data["at"]),
        subject=data.get("subject", ""),
        changes=[
            FileChange(path=path, added=added, deleted=deleted, old_path=old_path)
            for path, added, deleted, old_path in data.get("changes", [])
        ],
        parents=tuple(data.get("parents", ())),
    )


def write_snapshot(commits: Iterable[Commit], stream: IO[str]) -> int:
    """Write a snapshot and return how many commits it holds."""
    json.dump({"format": FORMAT_NAME, "version": FORMAT_VERSION}, stream)
    stream.write("\n")
    count = 0
    for commit in commits:
        json.dump(commit_to_dict(commit), stream, ensure_ascii=False)
        stream.write("\n")
        count += 1
    return count


def read_snapshot(stream: IO[str]) -> Iterator[Commit]:
    """Read commits back. Raises :class:`SnapshotError` on foreign or damaged data."""
    header_line = stream.readline()
    try:
        header = json.loads(header_line)
    except json.JSONDecodeError as exc:
        raise SnapshotError("not a snapshot: the header is not JSON") from exc
    if not isinstance(header, dict) or header.get("format") != FORMAT_NAME:
        raise SnapshotError("not a gitlog-insights snapshot")
    if header.get("version") != FORMAT_VERSION:
        raise SnapshotError(f"unsupported snapshot version {header.get('version')!r}")
    return _read_rows(stream)


def _read_rows(stream: IO[str]) -> Iterator[Commit]:
    for number, line in enumerate(stream, start=2):
        if not line.strip():
            continue
        try:
            yield commit_from_dict(json.loads(line))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise SnapshotError(f"snapshot line {number}: {exc}") from exc
