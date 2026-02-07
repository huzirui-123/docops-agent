"""Low-risk paragraph-level format fixer for optional consistency alignment."""

from __future__ import annotations

from typing import Any

from docx.document import Document as DocxDocument
from docx.shared import Pt

from core.format.models import FormatPolicy
from core.format.run_ids import iter_paragraph_run_contexts
from core.utils.docx_xml import get_first_line_indent_twips, get_line_spacing_twips


def safe_fix_document(
    document: DocxDocument, policy: FormatPolicy, touched_runs: set[str]
) -> list[dict[str, Any]]:
    """Apply low-risk paragraph fixes on touched body paragraphs only.

    Safe fixes:
    - first-line indent to policy.first_line_indent_twips (when expected is set)
    - line spacing to policy.line_spacing_twips

    Explicitly out of scope:
    - run text/font/size
    - table structure/cell content/style
    - paragraph insertion/removal
    """

    changes: list[dict[str, Any]] = []
    touched_paragraphs = _touched_body_paragraph_paths(touched_runs)
    if not touched_paragraphs:
        return changes

    for context in iter_paragraph_run_contexts(document, include_tables=False):
        paragraph_path = context.paragraph_path
        if paragraph_path not in touched_paragraphs:
            continue

        paragraph = context.paragraph

        if policy.first_line_indent_twips is not None:
            before_indent = get_first_line_indent_twips(paragraph)
            after_indent = policy.first_line_indent_twips
            if before_indent != after_indent:
                paragraph.paragraph_format.first_line_indent = Pt(after_indent / 20)
                changes.append(
                    {
                        "paragraph_path": paragraph_path,
                        "field": "first_line_indent_twips",
                        "before": before_indent,
                        "after": after_indent,
                        "reason": "safe_fix_to_effective_policy",
                    }
                )

        before_spacing = get_line_spacing_twips(paragraph)
        after_spacing = policy.line_spacing_twips
        if before_spacing != after_spacing:
            paragraph.paragraph_format.line_spacing = Pt(after_spacing / 20)
            changes.append(
                {
                    "paragraph_path": paragraph_path,
                    "field": "line_spacing_twips",
                    "before": before_spacing,
                    "after": after_spacing,
                    "reason": "safe_fix_to_effective_policy",
                }
            )

    return changes


def _touched_body_paragraph_paths(touched_runs: set[str]) -> set[str]:
    touched: set[str] = set()
    for run_id in touched_runs:
        paragraph_path, _sep, _rest = run_id.partition(":r")
        if paragraph_path.startswith("p"):
            touched.add(paragraph_path)
    return touched

