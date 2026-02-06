"""Data models for template parsing, fingerprinting, and map storage."""

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


@dataclass(frozen=True)
class FingerprintParagraph:
    """Paragraph text included in fingerprint payload."""

    paragraph_path: str
    text: str


@dataclass(frozen=True)
class FingerprintOccurrence:
    """Run-insensitive occurrence entry for fingerprint payload."""

    paragraph_path: str
    start: int
    end: int
    field_name: str


@dataclass(frozen=True)
class FingerprintUnsupported:
    """Unsupported placeholder entry in fingerprint payload."""

    kind: str
    text: str
    paragraph_path: str | None = None
    start: int | None = None
    end: int | None = None


@dataclass
class FingerprintPayload:
    """Canonical payload used for template fingerprint generation."""

    paragraphs: list[FingerprintParagraph] = field(default_factory=list)
    occurrences: list[FingerprintOccurrence] = field(default_factory=list)
    unsupported: list[FingerprintUnsupported] = field(default_factory=list)


@dataclass
class TemplateMapping:
    """Stored mapping metadata keyed by template fingerprint."""

    fingerprint: str
    fields: list[str] = field(default_factory=list)
    field_map: dict[str, str] = field(default_factory=dict)
    note: str | None = None


@dataclass
class TemplateMapStoreData:
    """On-disk JSON structure for template mappings."""

    version: int = 1
    templates: dict[str, TemplateMapping] = field(default_factory=dict)
