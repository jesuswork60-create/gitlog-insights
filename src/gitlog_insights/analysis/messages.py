"""What commit subjects say: conventional-commit types, fixes and reverts."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

from ..models import Commit

_CONVENTIONAL = re.compile(r"^(?P<type>[a-zA-Z]+)(?:\((?P<scope>[^)]*)\))?(?P<breaking>!)?:\s")
_FIX_WORDS = re.compile(r"\b(fix(es|ed)?|bug|hotfix|regression)\b", re.IGNORECASE)
_REVERT = re.compile(r'^revert\b', re.IGNORECASE)
_MERGE = re.compile(r"^merge\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ParsedSubject:
    kind: str
    scope: str | None = None
    breaking: bool = False


def classify_subject(subject: str) -> ParsedSubject:
    """Read the conventional prefix if there is one, otherwise guess from wording.

    The fallback kinds are ``revert``, ``merge``, ``fix`` and ``other``.
    """
    match = _CONVENTIONAL.match(subject)
    if match:
        return ParsedSubject(
            match["type"].lower(), match["scope"] or None, bool(match["breaking"])
        )
    if _REVERT.match(subject):
        return ParsedSubject("revert")
    if _MERGE.match(subject):
        return ParsedSubject("merge")
    if _FIX_WORDS.search(subject):
        return ParsedSubject("fix")
    return ParsedSubject("other")


@dataclass(slots=True)
class MessageStats:
    total: int = 0
    kinds: Counter[str] = field(default_factory=Counter)
    scopes: Counter[str] = field(default_factory=Counter)
    breaking: int = 0
    empty_subjects: int = 0
    long_subjects: int = 0
    fix_touches: Counter[str] = field(default_factory=Counter)

    @property
    def fix_ratio(self) -> float:
        return self.kinds["fix"] / self.total if self.total else 0.0


def message_stats(commits: Iterable[Commit], *, long_subject: int = 72) -> MessageStats:
    """Tally subjects, and count per file how many fix commits touched it."""
    stats = MessageStats()
    for commit in commits:
        parsed = classify_subject(commit.subject)
        stats.total += 1
        stats.kinds[parsed.kind] += 1
        if parsed.scope:
            stats.scopes[parsed.scope] += 1
        if parsed.breaking:
            stats.breaking += 1
        if not commit.subject.strip():
            stats.empty_subjects += 1
        if len(commit.subject) > long_subject:
            stats.long_subjects += 1
        if parsed.kind == "fix":
            stats.fix_touches.update(set(commit.paths))
    return stats
