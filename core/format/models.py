"""Data models for formatting policy, issues, and reports."""

from __future__ import annotations

from typing import Any, Literal

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
    first_line_indent_twips: int | None
    twips_tolerance: int
    treat_inherited_as_error: bool = False
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
    expected: Any | None = None
    actual: Any | None = None
    tolerance: int | None = None
    template_value: Any | None = None
    rendered_value: Any | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    severity: Literal["error", "warn"] = "error"
    observability: Literal["observed", "unknown"] = "observed"


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
    baseline: Literal["template", "policy"]
    effective_policy_overrides: dict[str, Any] = Field(default_factory=dict)
    diagnostics: dict[str, Any] | None = None
    fix_applied: bool = False
    fix_changes: list[dict[str, Any]] = Field(default_factory=list)
    skipped: bool


class FormatReport(BaseModel):
    """Validation/fix report.

    Rules:
    - passed == (error_count == 0)
    - error_count counts unresolved severity=error issues
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
        unresolved = sum(
            1 for issue in issues if not issue.fixed and issue.severity == "error"
        )
        fixed_count = sum(1 for issue in issues if issue.fixed)
        return cls(
            passed=unresolved == 0,
            error_count=unresolved,
            fixed_count=fixed_count,
            issues=issues,
        )
