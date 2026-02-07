"""Human-readable formatting summary rendering for CLI output."""

from __future__ import annotations

from collections import Counter
from typing import Literal

from core.format.models import FormatSummary
from core.render.models import RenderOutput


def render_format_summary(
    output: RenderOutput, format_fix_mode: Literal["none", "safe"]
) -> str:
    """Render one-screen human-readable format summary."""

    report = output.format_report
    summary = report.summary
    if summary is None:
        return "format summary unavailable"

    lines: list[str] = []
    lines.append("format_summary:")
    lines.append(
        f"format_mode={summary.mode} format_fix_mode={format_fix_mode} "
        f"format_baseline={summary.baseline}"
    )
    lines.append(f"result={'PASSED' if report.passed else 'FAILED'}")

    if summary.skipped or summary.mode == "off":
        lines.append("format skipped: only replacement performed")
        lines.append("suggestion: none")
        return "\n".join(lines)

    template_has_tables = summary.template_observed.has_tables
    rendered_has_tables = summary.rendered_observed.has_tables
    lines.append(f"observed: has_tables {template_has_tables}->{rendered_has_tables}")

    template_indent = _dominant_indent(summary.template_observed.first_line_indent_twips_hist)
    rendered_indent = _dominant_indent(summary.rendered_observed.first_line_indent_twips_hist)
    lines.append(f"dominant_indent: {template_indent}->{rendered_indent}")

    issue_counter: Counter[str] = Counter(issue.code for issue in report.issues)
    if issue_counter:
        top_items = sorted(issue_counter.items(), key=lambda item: (-item[1], item[0]))[:5]
        issues_text = ", ".join(f"{code}={count}" for code, count in top_items)
        lines.append(f"issues: {issues_text}")
    else:
        lines.append("issues: none")

    if summary.fix_applied and summary.fix_changes:
        lines.append(f"fix: applied {len(summary.fix_changes)} changes")
        for change in summary.fix_changes[:3]:
            paragraph_path = str(change.get("paragraph_path", "unknown"))
            field = str(change.get("field", "unknown"))
            before = _to_string(change.get("before"))
            after = _to_string(change.get("after"))
            lines.append(f"fix_change: {paragraph_path} {field} {before}->{after}")
    else:
        lines.append("fix: none")

    lines.append(
        "suggestion: "
        + _build_suggestion(
            issue_counter=issue_counter,
            summary=summary,
            template_indent=template_indent,
        )
    )
    return "\n".join(lines)


def _dominant_indent(indent_hist: dict[str, int]) -> str:
    if not indent_hist:
        return "none"
    dominant_key = sorted(indent_hist.items(), key=lambda item: (-item[1], item[0]))[0][0]
    return dominant_key


def _build_suggestion(
    *, issue_counter: Counter[str], summary: FormatSummary, template_indent: str
) -> str:
    if not issue_counter:
        return "none"

    if "TABLE_FORBIDDEN" in issue_counter:
        return "use --format-baseline template or --export-suggested-policy"

    if "FIRST_LINE_INDENT_MISMATCH" in issue_counter:
        if template_indent != "none":
            return (
                f"template dominant indent is {template_indent}; consider --format-baseline "
                "template or adjust twips_tolerance"
            )
        return "consider --format-baseline template or adjust first_line_indent_twips/tolerance"

    diagnostics = summary.diagnostics
    if isinstance(diagnostics, dict):
        by_code = diagnostics.get("by_code")
        if isinstance(by_code, dict):
            for code in sorted(issue_counter.keys()):
                bucket = by_code.get(code)
                if isinstance(bucket, dict):
                    suggestions = bucket.get("suggestions")
                    if isinstance(suggestions, list) and suggestions:
                        first = suggestions[0]
                        if isinstance(first, str) and first.strip():
                            return first.strip()

    return "review out.format_report.json diagnostics and adjust template/policy"


def _to_string(value: object) -> str:
    if value is None:
        return "none"
    return str(value)
