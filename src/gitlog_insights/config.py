"""Optional per-repository settings from ``.gitlog-insights.toml``.

.. code-block:: toml

    [filters]
    exclude = ["vendor/", "*.lock"]
    exclude_authors = ["release-bot"]

    [identity]
    mailmap = ".mailmap"

    [identity.aliases]
    "old@example.com" = "new@example.com"

    [cochange]
    min_support = 3
    max_files = 30

    [hotspots]
    half_life_days = 90

Unknown sections and keys are errors, because a misspelt filter that silently
does nothing produces reports that look fine and are wrong.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from typing import Any

DEFAULT_FILE_NAME = ".gitlog-insights.toml"


class ConfigError(ValueError):
    pass


@dataclass(slots=True)
class Config:
    exclude: tuple[str, ...] = ()
    include: tuple[str, ...] = ()
    exclude_authors: tuple[str, ...] = ()
    mailmap: str | None = None
    aliases: dict[str, str] = field(default_factory=dict)
    min_support: int = 2
    max_files: int = 30
    half_life_days: float = 90.0


def _string_list(section: str, key: str, value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"[{section}] {key} must be a list of strings")
    return tuple(value)


def _positive_int(section: str, key: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"[{section}] {key} must be a positive integer")
    return value


def _reject_unknown(section: str, table: dict, known: set[str]) -> None:
    unknown = sorted(set(table) - known)
    if unknown:
        raise ConfigError(f"[{section}] unknown key(s): {', '.join(unknown)}")


def parse_config(data: dict[str, Any]) -> Config:
    """Validate a decoded TOML document."""
    config = Config()
    _reject_unknown("top level", data, {"filters", "identity", "cochange", "hotspots"})

    filters = data.get("filters", {})
    _reject_unknown("filters", filters, {"exclude", "include", "exclude_authors"})
    if "exclude" in filters:
        config.exclude = _string_list("filters", "exclude", filters["exclude"])
    if "include" in filters:
        config.include = _string_list("filters", "include", filters["include"])
    if "exclude_authors" in filters:
        config.exclude_authors = _string_list(
            "filters", "exclude_authors", filters["exclude_authors"]
        )

    identity = data.get("identity", {})
    _reject_unknown("identity", identity, {"mailmap", "aliases"})
    if "mailmap" in identity:
        if not isinstance(identity["mailmap"], str):
            raise ConfigError("[identity] mailmap must be a string")
        config.mailmap = identity["mailmap"]
    aliases = identity.get("aliases", {})
    if not isinstance(aliases, dict) or not all(isinstance(v, str) for v in aliases.values()):
        raise ConfigError("[identity.aliases] must map emails to emails")
    config.aliases = dict(aliases)

    cochange = data.get("cochange", {})
    _reject_unknown("cochange", cochange, {"min_support", "max_files"})
    if "min_support" in cochange:
        config.min_support = _positive_int("cochange", "min_support", cochange["min_support"])
    if "max_files" in cochange:
        config.max_files = _positive_int("cochange", "max_files", cochange["max_files"])

    hotspots = data.get("hotspots", {})
    _reject_unknown("hotspots", hotspots, {"half_life_days"})
    if "half_life_days" in hotspots:
        value = hotspots["half_life_days"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ConfigError("[hotspots] half_life_days must be a positive number")
        config.half_life_days = float(value)
    return config


def load_config(path: str) -> Config:
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc.strerror}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    try:
        return parse_config(data)
    except ConfigError as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def discover_config(repo: str | None) -> Config:
    """Load the repository's default config file if it has one."""
    if repo:
        candidate = os.path.join(repo, DEFAULT_FILE_NAME)
        if os.path.isfile(candidate):
            return load_config(candidate)
    return Config()
