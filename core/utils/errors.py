"""Custom exceptions for core logic."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.format.models import FormatReport
    from core.render.models import RenderOutput, ReplaceReport
    from core.templates.models import ParseResult


class TemplateError(Exception):
    """Raised when template placeholders are unsupported in strict/error mode."""

    def __init__(
        self,
        message: str,
        *,
        result: ParseResult | None = None,
        replace_report: ReplaceReport | None = None,
        render_output: RenderOutput | None = None,
    ) -> None:
        super().__init__(message)
        self.result = result
        self.replace_report = replace_report
        self.render_output = render_output


class MissingRequiredFieldsError(Exception):
    """Raised when required fields are missing after render."""

    def __init__(
        self,
        message: str,
        *,
        missing_required: list[str],
        render_output: RenderOutput | None = None,
    ) -> None:
        super().__init__(message)
        self.missing_required = missing_required
        self.render_output = render_output


class FormatValidationError(Exception):
    """Raised when format validation fails in strict execution paths."""

    def __init__(self, message: str, *, format_report: FormatReport | None = None) -> None:
        super().__init__(message)
        self.format_report = format_report
