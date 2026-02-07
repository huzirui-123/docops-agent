"""Suggested policy export helpers."""

from __future__ import annotations

from typing import Any

from docx.document import Document as DocxDocument

from core.format.models import FormatPolicy
from core.format.observed import dominant_first_line_indent_twips


def build_suggested_policy(template_document: DocxDocument, policy: FormatPolicy) -> dict[str, Any]:
    """Build a minimal suggested policy using template baseline observations."""

    return {
        "forbid_tables": False if template_document.tables else policy.forbid_tables,
        "first_line_indent_twips": dominant_first_line_indent_twips(template_document),
        "twips_tolerance": policy.twips_tolerance,
    }

