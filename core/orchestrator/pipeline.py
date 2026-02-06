"""Orchestration pipeline for deterministic skill-driven rendering."""

from __future__ import annotations

from typing import Literal

from docx.document import Document as DocxDocument

from core.format.fixer import fix_document
from core.format.models import FormatPolicy
from core.format.validator import validate_document
from core.render.docx_renderer import render_docx
from core.render.models import RenderOutput
from core.skills.base import Skill
from core.skills.models import TaskSpec
from core.utils.errors import MissingRequiredFieldsError


def run_task(
    task_spec: TaskSpec,
    template_document: DocxDocument,
    skill: Skill,
    policy: FormatPolicy,
    unsupported_mode: Literal["error", "warn"] = "error",
) -> RenderOutput:
    """Execute skill -> render -> fix -> validate pipeline."""

    skill_result = skill.build_fields(task_spec)
    output = render_docx(
        document=template_document,
        skill_result=skill_result,
        unsupported_mode=unsupported_mode,
    )

    touched_runs = set(output.replace_report.touched_runs)
    fix_document(output.document, policy, touched_runs)
    output.format_report = validate_document(output.document, policy, touched_runs)

    if output.missing_fields.missing_required:
        raise MissingRequiredFieldsError(
            "Missing required template fields",
            missing_required=output.missing_fields.missing_required,
            render_output=output,
        )

    return output
