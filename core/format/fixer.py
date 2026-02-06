"""Format fixer that applies safe, policy-bounded corrections."""

from __future__ import annotations

from docx.document import Document as DocxDocument

from core.format.models import FormatIssue, FormatPolicy, FormatReport
from core.format.run_ids import ParagraphRunContext, iter_paragraph_run_contexts
from core.utils.docx_xml import (
    get_run_east_asia_font,
    paragraph_has_direct_numpr,
    remove_paragraph_direct_numpr,
    set_run_fonts_and_size,
)


def fix_document(
    document: DocxDocument, policy: FormatPolicy, touched_runs: set[str]
) -> FormatReport:
    """Apply fixable formatting corrections.

    Notes:
    - Tables are never fixed when forbid_tables is true.
    - numPr handling only touches direct pPr.numPr.
    """

    issues: list[FormatIssue] = []

    if policy.forbid_tables and document.tables:
        for table_index, _ in enumerate(document.tables):
            issues.append(
                FormatIssue(
                    code="TABLE_FORBIDDEN",
                    message="Tables are forbidden by policy.",
                    paragraph_path=f"t{table_index}",
                    fixable=False,
                    fixed=False,
                )
            )

    include_tables = not policy.forbid_tables
    for context in iter_paragraph_run_contexts(document, include_tables=include_tables):
        issues.extend(_fix_paragraph(context, policy, touched_runs))

    return FormatReport.from_issues(issues)


def _fix_paragraph(
    context: ParagraphRunContext, policy: FormatPolicy, touched_runs: set[str]
) -> list[FormatIssue]:
    issues: list[FormatIssue] = []
    paragraph = context.paragraph

    if policy.forbid_numpr and paragraph_has_direct_numpr(paragraph):
        fixed = remove_paragraph_direct_numpr(paragraph)
        issues.append(
            FormatIssue(
                code="NUMPR_PRESENT",
                message="Direct paragraph numbering (pPr.numPr) is present.",
                paragraph_path=context.paragraph_path,
                fixable=True,
                fixed=fixed,
            )
        )

    if policy.trim_leading_spaces:
        changed = _trim_paragraph_leading_whitespace(paragraph, set(policy.trim_chars))
        if changed:
            issues.append(
                FormatIssue(
                    code="LEADING_WHITESPACE",
                    message="Paragraph leading whitespace trimmed.",
                    paragraph_path=context.paragraph_path,
                    fixable=True,
                    fixed=True,
                )
            )

    for run_id, run in zip(context.run_ids, paragraph.runs, strict=False):
        if run_id not in touched_runs:
            continue

        current_latin = run.font.name
        current_east = get_run_east_asia_font(run)
        current_size = run.font.size.pt if run.font.size is not None else None

        needs_font_fix = (
            current_latin != policy.run_font_latin or current_east != policy.run_font_east_asia
        )
        needs_size_fix = current_size is None or round(current_size) != policy.run_size_pt

        if needs_font_fix or needs_size_fix:
            set_run_fonts_and_size(
                run,
                latin_font=policy.run_font_latin,
                east_asia_font=policy.run_font_east_asia,
                size_pt=policy.run_size_pt,
            )

        if needs_font_fix:
            issues.append(
                FormatIssue(
                    code="RUN_FONT_MISMATCH",
                    message="Touched run font was corrected.",
                    paragraph_path=context.paragraph_path,
                    run_id=run_id,
                    fixable=True,
                    fixed=True,
                )
            )

        if needs_size_fix:
            issues.append(
                FormatIssue(
                    code="RUN_SIZE_MISMATCH",
                    message="Touched run size was corrected.",
                    paragraph_path=context.paragraph_path,
                    run_id=run_id,
                    fixable=True,
                    fixed=True,
                )
            )

    return issues


def _trim_paragraph_leading_whitespace(paragraph, trim_chars: set[str]) -> bool:
    """Trim leading whitespace across runs using policy trim chars."""

    changed = False
    trimming = True

    for run in paragraph.runs:
        text = run.text or ""
        if not text:
            continue

        if not trimming:
            break

        index = 0
        while index < len(text) and text[index] in trim_chars:
            index += 1

        if index == 0:
            trimming = False
            break

        run.text = text[index:]
        changed = True

        if index < len(text):
            trimming = False
            break

    return changed
