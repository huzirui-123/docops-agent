"""Custom exceptions for core logic."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.templates.models import ParseResult


class TemplateError(Exception):
    """Raised when template placeholders are unsupported in strict mode."""

    def __init__(self, message: str, *, result: ParseResult | None = None) -> None:
        super().__init__(message)
        self.result = result
