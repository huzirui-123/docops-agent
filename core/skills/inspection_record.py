"""Inspection record skill without LLM dependencies."""

from __future__ import annotations

from core.skills.helpers import build_skill_result
from core.skills.models import SkillResult, TaskSpec
from core.skills.specs import INSPECTION_RECORD_SPEC


class InspectionRecordSkill:
    """Deterministically maps inspection payload fields to placeholders."""

    name = "inspection_record"

    def build_fields(self, task: TaskSpec) -> SkillResult:
        return build_skill_result(task, INSPECTION_RECORD_SPEC)
