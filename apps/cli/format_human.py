"""Human-readable formatting summary rendering for CLI output."""

from __future__ import annotations

from collections import Counter
from typing import Literal

from core.format.models import FormatSummary
from core.render.models import RenderOutput


def render_format_summary(
    output: RenderOutput,
    format_fix_mode: Literal["none", "safe"],
    *,
    command_base: str,
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
        lines.append("next_cmd: none")
        return "\n".join(lines)

    template_has_tables = summary.template_observed.has_tables
    rendered_has_tables = summary.rendered_observed.has_tables
    lines.append(f"observed: has_tables {template_has_tables}->{rendered_has_tables}")

    template_indent = _dominant_indent(summary.template_observed.first_line_indent_twips_hist)
    rendered_indent = _dominant_indent(summary.rendered_observed.first_line_indent_twips_hist)
    lines.append(f"dominant_indent: {template_indent}->{rendered_indent}")

    issue_counter: Counter[str] = Counter(issue.code for issue in report.issues)
    error_counter: Counter[str] = Counter(
        issue.code for issue in report.issues if issue.severity == "error"
    )
    warning_counter: Counter[str] = Counter(
        issue.code for issue in report.issues if issue.severity == "warn"
    )
    if issue_counter:
        top_items = sorted(issue_counter.items(), key=lambda item: (-item[1], item[0]))[:5]
        issues_text = ", ".join(f"{code}={count}" for code, count in top_items)
        lines.append(f"issues: {issues_text}")
    else:
        lines.append("issues: none")
    if error_counter:
        top_errors = sorted(error_counter.items(), key=lambda item: (-item[1], item[0]))[:5]
        errors_text = ", ".join(f"{code}={count}" for code, count in top_errors)
        lines.append(f"errors: {errors_text}")
    else:
        lines.append("errors: none")
    if warning_counter:
        top_warnings = sorted(
            warning_counter.items(), key=lambda item: (-item[1], item[0])
        )[:5]
        warnings_text = ", ".join(f"{code}={count}" for code, count in top_warnings)
        lines.append(f"warnings: {warnings_text}")
    else:
        lines.append("warnings: none")

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
            error_counter=error_counter,
            warning_counter=warning_counter,
            summary=summary,
        )
    )
    lines.append(
        "next_cmd: "
        + _build_next_cmd(
            error_counter=error_counter,
            warning_counter=warning_counter,
            summary=summary,
            command_base=command_base,
        )
    )
    return "\n".join(lines)


def _dominant_indent(indent_hist: dict[str, int]) -> str:
    if not indent_hist:
        return "none"
    dominant_key = sorted(indent_hist.items(), key=lambda item: (-item[1], item[0]))[0][0]
    return dominant_key


def _build_suggestion(
    *,
    error_counter: Counter[str],
    warning_counter: Counter[str],
    summary: FormatSummary,
) -> str:
    has_errors = bool(error_counter)
    has_warnings = bool(warning_counter)
    if not has_errors and not has_warnings:
        return "none"

    if has_errors:
        if summary.mode != "strict":
            return (
                "error-level issues detected; try --preset strict for gatekeeping. "
                "Use --format-report json for quieter output."
            )
        return (
            "strict mode failed on error-level issues; try --preset template "
            "or adjust policy. Use --format-report json for quieter output."
        )

    if summary.baseline != "template":
        return (
            "warn-only issues detected; output is usable. "
            "Try --format-baseline template. Use --format-report json for quieter output."
        )

    return (
        "warn-only issues detected; output is usable. "
        "Try --preset template. Use --format-report json for quieter output."
    )


def _build_next_cmd(
    *,
    error_counter: Counter[str],
    warning_counter: Counter[str],
    summary: FormatSummary,
    command_base: str,
) -> str:
    has_errors = bool(error_counter)
    has_warnings = bool(warning_counter)
    if not has_errors and not has_warnings:
        return "none"

    if has_errors:
        if summary.mode != "strict":
            return f"{command_base} --preset strict"
        return f"{command_base} --preset template"

    if summary.baseline != "template":
        return f"{command_base} --format-baseline template"
    return f"{command_base} --preset template"


def _to_string(value: object) -> str:
    if value is None:
        return "none"
    return str(value)
