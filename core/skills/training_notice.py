"""Training notice skill without LLM dependencies."""

from __future__ import annotations

from core.skills.helpers import build_skill_result
from core.skills.models import SkillResult, TaskSpec
from core.skills.specs import TRAINING_NOTICE_SPEC


class TrainingNoticeSkill:
    """Deterministically maps training payload fields to placeholders."""

    name = "training_notice"

    def build_fields(self, task: TaskSpec) -> SkillResult:
        return build_skill_result(task, TRAINING_NOTICE_SPEC)
