"""Meeting notice skill without LLM dependencies."""

from __future__ import annotations

from core.skills.helpers import build_skill_result
from core.skills.models import SkillResult, TaskSpec
from core.skills.specs import MEETING_NOTICE_SPEC


class MeetingNoticeSkill:
    """Deterministically maps meeting payload fields to template placeholders."""

    name = "meeting_notice"

    def build_fields(self, task: TaskSpec) -> SkillResult:
        return build_skill_result(task, MEETING_NOTICE_SPEC)
