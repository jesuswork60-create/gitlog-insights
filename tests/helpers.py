"""Small builders shared by the test modules. All data here is made up."""

from __future__ import annotations

from datetime import datetime, timezone

from gitlog_insights.models import Author, Commit, FileChange

ALPHA = Author("Alpha Dev", "alpha@example.com")
BETA = Author("Beta Dev", "beta@example.com")
GAMMA = Author("Gamma Dev", "gamma@example.com")


def at(day: int, hour: int = 12, month: int = 3, year: int = 2024) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def change(path: str, added: int | None = 1, deleted: int | None = 0, old: str | None = None) -> FileChange:
    return FileChange(path, added, deleted, old)


def commit(
    sha: str,
    when: datetime,
    *changes: FileChange,
    author: Author = ALPHA,
    subject: str = "change",
    parents: tuple[str, ...] = ("p",),
) -> Commit:
    return Commit(sha, author, when, subject, list(changes), parents)


def log_lines(text: str) -> list[str]:
    """Split like reading a file does. ``str.splitlines`` would also break on \\x1e."""
    return text.split("\n")


MACHINE_LOG = (
    "\x1e" "c3" "\x1f" "c2" "\x1f" "Beta Dev" "\x1f" "beta@example.com" "\x1f"
    "2024-03-03T09:00:00+01:00" "\x1f" "feat(core): add parser\n"
    "\n"
    "10\t2\tsrc/core.py\n"
    "1\t0\tsrc/{old => new}/util.py\n"
    "-\t-\tassets/logo.png\n"
    "\x1e" "c2" "\x1f" "c1" "\x1f" "Alpha Dev" "\x1f" "alpha@example.com" "\x1f"
    "2024-03-02T09:00:00+00:00" "\x1f" "fix: repair core\n"
    "\n"
    "3\t3\tsrc/core.py\n"
    "\x1e" "c1" "\x1f" "\x1f" "Alpha Dev" "\x1f" "alpha@example.com" "\x1f"
    "2024-03-01T09:00:00+00:00" "\x1f" "initial import\n"
    "\n"
    "100\t0\tsrc/core.py\n"
    "20\t0\tsrc/old/util.py\n"
)

DEFAULT_LOG = """\
commit aaaaaaa1111111111111111111111111111111aa (HEAD -> main, tag: v1)
Merge: bbbbbbb ccccccc
Author: Alpha Dev <alpha@example.com>
Date:   Mon Mar 4 10:00:00 2024 +0100

    Merge branch 'topic'

commit bbbbbbb1111111111111111111111111111111bb
Author: Beta Dev <beta@example.com>
Date:   Sun Mar 3 10:00:00 2024 +0000

    Rewrite the loader

    A body line that looks like numstat is ignored because it is indented:
    1\t2\tnot/a/file.py

5\t1\tloader.py
0\t0\told.py => renamed.py
"""
