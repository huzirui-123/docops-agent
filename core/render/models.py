"""Render pipeline report models."""

from __future__ import annotations

from typing import Literal, cast

from docx.document import Document as DocxDocument
from pydantic import BaseModel, ConfigDict, Field

from core.format.models import FormatIssue, FormatReport
from core.templates.models import ParseResult


class ReplaceLogEntry(BaseModel):
    """Single replacement/unsupported/missing log item."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["replaced", "missing", "unsupported"]
    field_name: str | None = None
    run_id: str | None = None
    paragraph_path: str | None = None
    start: int | None = None
    end: int | None = None
    original_text: str | None = None
    new_text: str | None = None
    reason: str | None = None


class ReplaceSummary(BaseModel):
    """Aggregate replacement summary for observability."""

    model_config = ConfigDict(extra="forbid")

    total_placeholders: int
    replaced_count: int
    missing_count: int
    had_unsupported: bool
    unsupported_count: int
    unsupported_mode: Literal["error", "warn"]


class RunStyleSnapshot(BaseModel):
    """Captured template run style snapshot for touched runs."""

    model_config = ConfigDict(extra="forbid")

    latin_font: str | None = None
    east_asia_font: str | None = None
    size_pt: int | None = None


class ReplaceReport(BaseModel):
    """Full replacement report including touched runs."""

    model_config = ConfigDict(extra="forbid")

    entries: list[ReplaceLogEntry] = Field(default_factory=list)
    summary: ReplaceSummary
    touched_runs: list[str] = Field(default_factory=list)
    template_run_styles: dict[str, RunStyleSnapshot] = Field(default_factory=dict)


class MissingFieldsReport(BaseModel):
    """Missing fields split by required/optional sets."""

    model_config = ConfigDict(extra="forbid")

    missing_required: list[str] = Field(default_factory=list)
    missing_optional: list[str] = Field(default_factory=list)


class RenderOutput(BaseModel):
    """In-memory render output for M5 (no file paths)."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    document: DocxDocument
    parse_result: ParseResult
    template_fields: list[str]
    replace_report: ReplaceReport
    missing_fields: MissingFieldsReport
    format_report: FormatReport


def empty_format_report() -> FormatReport:
    """Build an empty, passing format report placeholder."""

    return FormatReport.from_issues(cast(list[FormatIssue], []))
