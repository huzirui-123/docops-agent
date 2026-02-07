"""Data models for formatting policy, issues, and reports."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FormatPolicy(BaseModel):
    """Formatting policy loaded from YAML."""

    model_config = ConfigDict(extra="forbid")

    forbid_tables: bool
    forbid_numpr: bool
    numpr_direct_only: bool
    run_font_latin: str
    run_font_east_asia: str
    run_size_pt: int
    line_spacing_twips: int
    first_line_indent_twips: int
    twips_tolerance: int
    trim_leading_spaces: bool
    trim_chars: list[str]


class FormatIssue(BaseModel):
    """Single formatting issue detected by validator/fixer."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    paragraph_path: str | None = None
    run_id: str | None = None
    fixable: bool
    fixed: bool = False


class FormatObserved(BaseModel):
    """Observed formatting characteristics of one document snapshot."""

    model_config = ConfigDict(extra="forbid")

    has_tables: bool
    has_numpr: bool
    first_line_indent_twips_hist: dict[str, int] = Field(default_factory=dict)
    run_font_latin_hist: dict[str, int] = Field(default_factory=dict)
    run_font_east_asia_hist: dict[str, int] = Field(default_factory=dict)


class FormatObservedDiff(BaseModel):
    """Difference between rendered and template observed formatting."""

    model_config = ConfigDict(extra="forbid")

    has_tables_changed: bool
    has_numpr_changed: bool
    first_line_indent_twips_hist_delta: dict[str, int] = Field(default_factory=dict)


class FormatSummary(BaseModel):
    """Observed summary attached to format reports."""

    model_config = ConfigDict(extra="forbid")

    template_observed: FormatObserved
    rendered_observed: FormatObserved
    diff: FormatObservedDiff
    mode: Literal["report", "strict", "off"]
    skipped: bool


class FormatReport(BaseModel):
    """Validation/fix report.

    Rules:
    - passed == (error_count == 0)
    - error_count counts unresolved issues (fixed == False), including non-fixable issues
    - fixed_count counts issues fixed during fixer stage
    """

    model_config = ConfigDict(extra="forbid")

    passed: bool
    error_count: int
    fixed_count: int
    issues: list[FormatIssue] = Field(default_factory=list)
    summary: FormatSummary | None = None

    @classmethod
    def from_issues(cls, issues: list[FormatIssue]) -> FormatReport:
        unresolved = sum(1 for issue in issues if not issue.fixed)
        fixed_count = sum(1 for issue in issues if issue.fixed)
        return cls(
            passed=unresolved == 0,
            error_count=unresolved,
            fixed_count=fixed_count,
            issues=issues,
        )
