"""Formatting diagnostics helpers for actionable report summaries."""

from __future__ import annotations

from typing import Any

from docx.document import Document as DocxDocument

from core.format.models import FormatIssue, FormatPolicy, FormatReport
from core.format.run_ids import iter_paragraph_run_contexts
from core.utils.docx_xml import get_first_line_indent_twips


def build_format_diagnostics(
    template_doc: DocxDocument,
    rendered_doc: DocxDocument,
    policy: FormatPolicy,
    format_report: FormatReport,
    max_examples: int = 5,
) -> dict[str, Any]:
    """Build grouped diagnostics with examples and user-action suggestions."""

    template_indent_by_path = _build_indent_lookup(template_doc)
    rendered_indent_by_path = _build_indent_lookup(rendered_doc)

    by_code: dict[str, dict[str, Any]] = {}
    for issue in format_report.issues:
        code = issue.code
        if code not in by_code:
            by_code[code] = {
                "count": 0,
                "examples": [],
                "suggestions": _suggestions_for_code(code, policy),
            }
        bucket = by_code[code]
        bucket["count"] += 1
        examples = bucket["examples"]
        if len(examples) < max_examples:
            examples.append(
                _build_example(
                    issue=issue,
                    template_indent_by_path=template_indent_by_path,
                    rendered_indent_by_path=rendered_indent_by_path,
                )
            )

    return {
        "issue_count": len(format_report.issues),
        "codes": sorted(by_code.keys()),
        "by_code": {code: by_code[code] for code in sorted(by_code.keys())},
    }


def _build_indent_lookup(document: DocxDocument) -> dict[str, int | None]:
    lookup: dict[str, int | None] = {}
    for context in iter_paragraph_run_contexts(document, include_tables=True):
        lookup[context.paragraph_path] = get_first_line_indent_twips(context.paragraph)
    return lookup


def _build_example(
    *,
    issue: FormatIssue,
    template_indent_by_path: dict[str, int | None],
    rendered_indent_by_path: dict[str, int | None],
) -> dict[str, Any]:
    example: dict[str, Any] = {
        "paragraph_path": issue.paragraph_path,
        "run_id": issue.run_id,
    }

    if issue.expected is not None:
        example["expected"] = issue.expected
    if issue.actual is not None:
        example["actual"] = issue.actual
    if issue.tolerance is not None:
        example["tolerance"] = issue.tolerance

    template_value = issue.template_value
    rendered_value = issue.rendered_value
    if issue.code == "FIRST_LINE_INDENT_MISMATCH" and issue.paragraph_path is not None:
        if template_value is None:
            template_value = template_indent_by_path.get(issue.paragraph_path)
        if rendered_value is None:
            rendered_value = rendered_indent_by_path.get(issue.paragraph_path)

    if template_value is not None:
        example["template_value"] = template_value
    if rendered_value is not None:
        example["rendered_value"] = rendered_value

    if issue.context:
        example["context"] = issue.context

    return example


def _suggestions_for_code(code: str, policy: FormatPolicy) -> list[str]:
    if code == "TABLE_FORBIDDEN":
        return [
            "Use --format-baseline template to validate against template shape.",
            "Or set policy.forbid_tables=false for table-based templates.",
        ]
    if code == "FIRST_LINE_INDENT_MISMATCH":
        return [
            (
                "Align policy.first_line_indent_twips with dominant template indent "
                f"(current policy={policy.first_line_indent_twips})."
            ),
            (
                "Increase policy.twips_tolerance for acceptable variance "
                f"(current tolerance={policy.twips_tolerance})."
            ),
        ]
    if code == "NUMPR_PRESENT":
        return [
            "Remove direct paragraph numbering (w:numPr) from the template.",
            "Keep numbering policy strict; this rule is direct XML only.",
        ]
    return ["Review this issue in out.format_report.json and adjust template/policy accordingly."]
