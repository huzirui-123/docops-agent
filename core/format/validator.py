"""Format validator using policy constraints and touched-run scope."""

from __future__ import annotations

from docx.document import Document as DocxDocument

from core.format.models import FormatIssue, FormatPolicy, FormatReport
from core.format.run_ids import ParagraphRunContext, iter_paragraph_run_contexts
from core.utils.docx_xml import (
    get_first_line_indent_twips,
    get_line_spacing_twips,
    get_run_east_asia_font,
    paragraph_has_direct_numpr,
)


def validate_document(
    document: DocxDocument, policy: FormatPolicy, touched_runs: set[str]
) -> FormatReport:
    """Validate document format with policy.

    Notes:
    - When forbid_tables is true, table presence is reported as non-fixable and
      table cell paragraphs are skipped for all other checks.
    - numPr checks only inspect direct pPr.numPr, not style inheritance.
    - When first_line_indent_twips is None, first-line indent validation is skipped.
    """

    issues: list[FormatIssue] = []

    if policy.forbid_tables and document.tables:
        table_count = len(document.tables)
        for table_index, _ in enumerate(document.tables):
            issues.append(
                FormatIssue(
                    code="TABLE_FORBIDDEN",
                    message="Tables are forbidden by policy.",
                    paragraph_path=f"t{table_index}",
                    fixable=False,
                    context={"table_count": table_count},
                )
            )

    include_tables = not policy.forbid_tables
    for context in iter_paragraph_run_contexts(document, include_tables=include_tables):
        issues.extend(_validate_paragraph(context, policy, touched_runs))

    return FormatReport.from_issues(issues)


def _validate_paragraph(
    context: ParagraphRunContext, policy: FormatPolicy, touched_runs: set[str]
) -> list[FormatIssue]:
    issues: list[FormatIssue] = []
    paragraph = context.paragraph

    if policy.forbid_numpr and paragraph_has_direct_numpr(paragraph):
        issues.append(
            FormatIssue(
                code="NUMPR_PRESENT",
                message="Direct paragraph numbering (pPr.numPr) is present.",
                paragraph_path=context.paragraph_path,
                fixable=True,
            )
        )

    actual_line_spacing = get_line_spacing_twips(paragraph)
    if actual_line_spacing is not None and not _within_tolerance(
        actual_line_spacing, policy.line_spacing_twips, policy.twips_tolerance
    ):
        issues.append(
            FormatIssue(
                code="LINE_SPACING_MISMATCH",
                message=(
                    f"Line spacing twips mismatch: expected {policy.line_spacing_twips}, "
                    f"got {actual_line_spacing}."
                ),
                paragraph_path=context.paragraph_path,
                fixable=False,
            )
        )

    if policy.first_line_indent_twips is not None:
        actual_indent = get_first_line_indent_twips(paragraph)
        if actual_indent is not None and not _within_tolerance(
            actual_indent, policy.first_line_indent_twips, policy.twips_tolerance
        ):
            issues.append(
                FormatIssue(
                    code="FIRST_LINE_INDENT_MISMATCH",
                    message=(
                        "First-line indent twips mismatch: "
                        f"expected {policy.first_line_indent_twips}, got {actual_indent}."
                    ),
                    paragraph_path=context.paragraph_path,
                    fixable=False,
                    expected=policy.first_line_indent_twips,
                    actual=actual_indent,
                    tolerance=policy.twips_tolerance,
                )
            )

    if policy.trim_leading_spaces and _has_leading_trim_chars(paragraph, set(policy.trim_chars)):
        issues.append(
            FormatIssue(
                code="LEADING_WHITESPACE",
                message="Paragraph has trim-target leading whitespace.",
                paragraph_path=context.paragraph_path,
                fixable=True,
            )
        )

    for run_id, run in zip(context.run_ids, paragraph.runs, strict=False):
        if run_id not in touched_runs:
            continue

        latin_font = run.font.name
        east_asia_font = get_run_east_asia_font(run)

        if latin_font != policy.run_font_latin or east_asia_font != policy.run_font_east_asia:
            issues.append(
                FormatIssue(
                    code="RUN_FONT_MISMATCH",
                    message=(
                        "Touched run font mismatch: "
                        f"latin={latin_font!r}, eastAsia={east_asia_font!r}."
                    ),
                    paragraph_path=context.paragraph_path,
                    run_id=run_id,
                    fixable=True,
                )
            )

        size = run.font.size.pt if run.font.size is not None else None
        if size is None or round(size) != policy.run_size_pt:
            issues.append(
                FormatIssue(
                    code="RUN_SIZE_MISMATCH",
                    message=(
                        f"Touched run size mismatch: expected {policy.run_size_pt}pt, got {size}."
                    ),
                    paragraph_path=context.paragraph_path,
                    run_id=run_id,
                    fixable=True,
                )
            )

    return issues


def _has_leading_trim_chars(paragraph, trim_chars: set[str]) -> bool:
    if not paragraph.runs:
        return False

    prefix = ""
    for run in paragraph.runs:
        prefix += run.text or ""
        if prefix:
            break

    return bool(prefix) and prefix[0] in trim_chars


def _within_tolerance(actual: int, expected: int, tolerance: int) -> bool:
    return abs(actual - expected) <= tolerance
