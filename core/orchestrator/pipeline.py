"""Orchestration pipeline for deterministic skill-driven rendering."""

from __future__ import annotations

from typing import Literal

from docx.document import Document as DocxDocument

from core.format.diagnostics import build_format_diagnostics
from core.format.fixer import fix_document
from core.format.models import FormatPolicy, FormatReport, FormatSummary
from core.format.observed import (
    diff_observed,
    dominant_first_line_indent_twips,
    observe_document,
)
from core.format.validator import validate_document
from core.render.docx_renderer import render_docx
from core.render.models import RenderOutput
from core.skills.base import Skill
from core.skills.models import TaskSpec
from core.utils.errors import MissingRequiredFieldsError

FormatMode = Literal["report", "strict", "off"]
FormatBaseline = Literal["template", "policy"]


def run_task(
    task_spec: TaskSpec,
    template_document: DocxDocument,
    skill: Skill,
    policy: FormatPolicy,
    unsupported_mode: Literal["error", "warn"] = "error",
    format_mode: FormatMode = "strict",
    format_baseline: FormatBaseline = "template",
) -> RenderOutput:
    """Execute skill -> render -> fix -> validate pipeline."""

    if format_mode not in {"report", "strict", "off"}:
        raise ValueError(f"Unsupported format mode: {format_mode}")
    if format_baseline not in {"template", "policy"}:
        raise ValueError(f"Unsupported format baseline: {format_baseline}")

    skill_result = skill.build_fields(task_spec)
    template_observed = observe_document(template_document)
    dominant_template_indent = dominant_first_line_indent_twips(template_document)
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
        effective_policy_overrides: dict[str, object] = {}
        diagnostics = None
    else:
        effective_policy, effective_policy_overrides = _build_effective_policy_for_validation(
            policy,
            template_observed,
            dominant_template_indent,
            format_baseline,
        )
        fix_document(output.document, policy, touched_runs)
        output.format_report = validate_document(output.document, effective_policy, touched_runs)
        diagnostics = build_format_diagnostics(
            template_doc=template_document,
            rendered_doc=output.document,
            policy=effective_policy,
            format_report=output.format_report,
        )

    rendered_observed = observe_document(output.document)
    output.format_report.summary = FormatSummary(
        template_observed=template_observed,
        rendered_observed=rendered_observed,
        diff=diff_observed(template_observed, rendered_observed),
        mode=format_mode,
        baseline=format_baseline,
        effective_policy_overrides=effective_policy_overrides,
        diagnostics=diagnostics,
        skipped=(format_mode == "off"),
    )

    if output.missing_fields.missing_required:
        raise MissingRequiredFieldsError(
            "Missing required template fields",
            missing_required=output.missing_fields.missing_required,
            render_output=output,
        )

    return output


def _build_effective_policy_for_validation(
    policy: FormatPolicy,
    template_observed,
    dominant_template_indent: int | None,
    format_baseline: FormatBaseline,
) -> tuple[FormatPolicy, dict[str, object]]:
    if format_baseline == "policy":
        return policy, {}

    effective_policy = policy.model_copy(deep=True)
    overrides: dict[str, object] = {}

    if template_observed.has_tables:
        if effective_policy.forbid_tables:
            overrides["forbid_tables"] = False
        effective_policy.forbid_tables = False

    if dominant_template_indent is None:
        if effective_policy.first_line_indent_twips is not None:
            overrides["first_line_indent_twips"] = None
        effective_policy.first_line_indent_twips = None
    else:
        if effective_policy.first_line_indent_twips != dominant_template_indent:
            overrides["first_line_indent_twips"] = dominant_template_indent
        effective_policy.first_line_indent_twips = dominant_template_indent

    return effective_policy, overrides
