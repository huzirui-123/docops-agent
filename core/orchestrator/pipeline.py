"""Orchestration pipeline for deterministic skill-driven rendering."""

from __future__ import annotations

from typing import Literal

from docx.document import Document as DocxDocument

from core.format.fixer import fix_document
from core.format.models import FormatPolicy, FormatReport, FormatSummary
from core.format.observed import diff_observed, observe_document
from core.format.validator import validate_document
from core.render.docx_renderer import render_docx
from core.render.models import RenderOutput
from core.skills.base import Skill
from core.skills.models import TaskSpec
from core.utils.errors import MissingRequiredFieldsError

FormatMode = Literal["report", "strict", "off"]


def run_task(
    task_spec: TaskSpec,
    template_document: DocxDocument,
    skill: Skill,
    policy: FormatPolicy,
    unsupported_mode: Literal["error", "warn"] = "error",
    format_mode: FormatMode = "strict",
) -> RenderOutput:
    """Execute skill -> render -> fix -> validate pipeline."""

    if format_mode not in {"report", "strict", "off"}:
        raise ValueError(f"Unsupported format mode: {format_mode}")

    skill_result = skill.build_fields(task_spec)
    template_observed = observe_document(template_document)
    output = render_docx(
        document=template_document,
        skill_result=skill_result,
        unsupported_mode=unsupported_mode,
    )

    touched_runs = set(output.replace_report.touched_runs)
    if format_mode == "off":
        output.format_report = FormatReport(
            passed=True,
            error_count=0,
            fixed_count=0,
            issues=[],
        )
    else:
        fix_document(output.document, policy, touched_runs)
        output.format_report = validate_document(output.document, policy, touched_runs)

    rendered_observed = observe_document(output.document)
    output.format_report.summary = FormatSummary(
        template_observed=template_observed,
        rendered_observed=rendered_observed,
        diff=diff_observed(template_observed, rendered_observed),
        mode=format_mode,
        skipped=(format_mode == "off"),
    )

    if output.missing_fields.missing_required:
        raise MissingRequiredFieldsError(
            "Missing required template fields",
            missing_required=output.missing_fields.missing_required,
            render_output=output,
        )

    return output
