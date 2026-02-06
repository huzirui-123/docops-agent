"""Data models for placeholder parsing."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Occurrence:
    """A supported placeholder that can be replaced in a single run."""

    field_name: str
    run_id: str
    start: int
    end: int


@dataclass(frozen=True)
class UnsupportedOccurrence:
    """A placeholder-like token that cannot be safely processed."""

    kind: str
    text: str
    run_id: str | None
    start: int | None
    end: int | None


@dataclass
class ParseResult:
    """Placeholder parsing output."""

    fields: list[str] = field(default_factory=list)
    occurrences: list[Occurrence] = field(default_factory=list)
    unsupported: list[UnsupportedOccurrence] = field(default_factory=list)
