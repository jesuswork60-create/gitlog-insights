"""The neutral report structure that analyses are translated into."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Column:
    key: str
    title: str
    align: str = "right"
    digits: int = 2  # decimal places when the value is a float in human formats


@dataclass(slots=True)
class Section:
    key: str
    title: str
    columns: list[Column]
    rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class Report:
    name: str
    sections: list[Section] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
