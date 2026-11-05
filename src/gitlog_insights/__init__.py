"""Parse ``git log`` output and report on how a repository changes over time."""

from .models import Author, Commit, FileChange
from .parser import LogParseError, LogParser, parse_log

__all__ = [
    "Author",
    "Commit",
    "FileChange",
    "LogParseError",
    "LogParser",
    "parse_log",
]

__version__ = "0.1.0"
