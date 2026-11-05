"""Parsing of ``--numstat`` rows, including rename notation and quoted paths."""

from __future__ import annotations

import re

from .models import FileChange

_ROW = re.compile(r"^(\d+|-)\t(\d+|-)\t(.+)$")
_BRACE_RENAME = re.compile(r"^(.*)\{(.*) => (.*)\}(.*)$")

_SIMPLE_ESCAPES = {
    "a": 0x07,
    "b": 0x08,
    "f": 0x0C,
    "n": 0x0A,
    "r": 0x0D,
    "t": 0x09,
    "v": 0x0B,
    "\\": 0x5C,
    '"': 0x22,
}


def unquote_path(text: str) -> str:
    """Undo git's C-style path quoting; unquoted text is returned unchanged.

    Git quotes a path containing control characters (and, unless
    ``core.quotePath`` is off, non-ASCII bytes) as ``"caf\\303\\251.txt"``, where
    the octal escapes are raw UTF-8 bytes.
    """
    if len(text) < 2 or not (text.startswith('"') and text.endswith('"')):
        return text
    body = text[1:-1]
    out = bytearray()
    i = 0
    while i < len(body):
        ch = body[i]
        if ch != "\\":
            out.extend(ch.encode("utf-8"))
            i += 1
            continue
        i += 1
        if i >= len(body):
            out.append(0x5C)
            break
        esc = body[i]
        if esc in _SIMPLE_ESCAPES:
            out.append(_SIMPLE_ESCAPES[esc])
            i += 1
        elif esc in "01234567":
            octal = body[i : i + 3]
            out.append(int(octal, 8) & 0xFF)
            i += len(octal)
        else:
            out.extend(("\\" + esc).encode("utf-8"))
            i += 1
    return out.decode("utf-8", errors="replace")


def _join(prefix: str, middle: str, suffix: str) -> str:
    """Concatenate brace-rename pieces, collapsing the slash an empty side leaves."""
    joined = prefix + middle + suffix
    return re.sub(r"/{2,}", "/", joined).lstrip("/") if not middle else joined


def split_rename(raw: str) -> tuple[str | None, str]:
    """Return ``(old_path, new_path)``; ``old_path`` is ``None`` for non-renames."""
    match = _BRACE_RENAME.match(raw)
    if match:
        prefix, old, new, suffix = match.groups()
        return _join(prefix, old, suffix), _join(prefix, new, suffix)
    if " => " in raw:
        old, new = raw.split(" => ", 1)
        return unquote_path(old), unquote_path(new)
    return None, unquote_path(raw)


def parse_numstat(line: str) -> FileChange | None:
    """Parse one row, or return ``None`` when the line is not a numstat row."""
    match = _ROW.match(line)
    if not match:
        return None
    added_text, deleted_text, raw_path = match.groups()
    old_path, path = split_rename(raw_path)
    added = None if added_text == "-" else int(added_text)
    deleted = None if deleted_text == "-" else int(deleted_text)
    return FileChange(path=path, added=added, deleted=deleted, old_path=old_path)
