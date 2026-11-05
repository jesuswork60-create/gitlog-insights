"""Merge the many spellings of one contributor: ``.mailmap`` files and aliases."""

from __future__ import annotations

import re
from typing import Iterable, Iterator, Mapping

from .models import Author, Commit

_MAILMAP_ENTRY = re.compile(
    r"^(?P<name1>[^<]*?)\s*<(?P<email1>[^>]*)>"
    r"(?:\s*(?P<name2>[^<]*?)\s*<(?P<email2>[^>]*)>)?\s*$"
)


class MailmapError(ValueError):
    pass


class Mailmap:
    """A parsed ``.mailmap``, covering the four forms git documents:

    .. code-block:: text

        Proper Name <commit@example.com>
        <proper@example.com> <commit@example.com>
        Proper Name <proper@example.com> <commit@example.com>
        Proper Name <proper@example.com> Commit Name <commit@example.com>

    Lookups try the name-and-email entry first, then the email-only one, so a
    more specific rule wins whatever order the file lists them in.
    """

    def __init__(self) -> None:
        self._by_email: dict[str, tuple[str | None, str | None]] = {}
        self._by_name_email: dict[tuple[str, str], tuple[str | None, str | None]] = {}

    @classmethod
    def parse(cls, text: str) -> "Mailmap":
        mailmap = cls()
        for number, raw in enumerate(text.splitlines(), start=1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            match = _MAILMAP_ENTRY.match(line)
            if not match:
                raise MailmapError(f"mailmap line {number}: cannot parse {raw!r}")
            mailmap._add(match)
        return mailmap

    def _add(self, match: re.Match[str]) -> None:
        name1 = match["name1"] or None
        email1 = match["email1"] or None
        name2 = match["name2"] or None
        email2 = match["email2"]
        if email2 is None:
            # "Proper Name <commit@email>": correct the name only.
            self._by_email[(email1 or "").lower()] = (name1, None)
        elif name2:
            self._by_name_email[(name2.lower(), email2.lower())] = (name1, email1)
        else:
            self._by_email[email2.lower()] = (name1, email1)

    def resolve(self, author: Author) -> Author:
        email = author.email.lower()
        rule = self._by_name_email.get((author.name.lower(), email))
        if rule is None:
            rule = self._by_email.get(email)
        if rule is None:
            return author
        name, new_email = rule
        return Author(name or author.name, new_email or author.email)

    def __len__(self) -> int:
        return len(self._by_email) + len(self._by_name_email)


class IdentityResolver:
    """Applies a mailmap, then simple email-to-email aliases from configuration."""

    def __init__(
        self,
        mailmap: Mailmap | None = None,
        aliases: Mapping[str, str] | None = None,
    ) -> None:
        self._mailmap = mailmap
        self._aliases = {k.lower(): v for k, v in (aliases or {}).items()}
        self._memo: dict[Author, Author] = {}

    def resolve(self, author: Author) -> Author:
        known = self._memo.get(author)
        if known is not None:
            return known
        resolved = author
        if self._mailmap is not None:
            resolved = self._mailmap.resolve(resolved)
        target = self._aliases.get(resolved.email.lower())
        if target is not None:
            resolved = Author(resolved.name, target)
        self._memo[author] = resolved
        return resolved

    def apply(self, commits: Iterable[Commit]) -> Iterator[Commit]:
        for commit in commits:
            resolved = self.resolve(commit.author)
            yield commit if resolved is commit.author else commit.with_author(resolved)
