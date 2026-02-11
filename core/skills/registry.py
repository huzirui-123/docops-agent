"""Skill registry for CLI/API skill resolution."""

from __future__ import annotations

from collections.abc import Callable

from core.skills.base import Skill
from core.skills.inspection_record import InspectionRecordSkill
from core.skills.meeting_notice import MeetingNoticeSkill
from core.skills.models import supported_task_types
from core.skills.training_notice import TrainingNoticeSkill

SkillFactory = Callable[[], Skill]

_SUPPORTED_SKILLS: dict[str, SkillFactory] = {
    "inspection_record": InspectionRecordSkill,
    "meeting_notice": MeetingNoticeSkill,
    "training_notice": TrainingNoticeSkill,
}


def create_skill(name: str) -> Skill:
    """Instantiate a supported skill by name."""

    try:
        factory = _SUPPORTED_SKILLS[name]
    except KeyError as exc:
        raise ValueError(f"Unsupported skill: {name}") from exc
    return factory()


def list_supported_skills() -> list[str]:
    """Return supported skill names in stable order."""

    return sorted(_SUPPORTED_SKILLS)


def _assert_registry_alignment() -> None:
    """Fail fast when task model support diverges from skill registry keys."""

    skill_names = set(_SUPPORTED_SKILLS)
    task_types = set(supported_task_types())
    if skill_names != task_types:
        raise RuntimeError(
            "Skill registry keys must match task type schemas: "
            f"skills={sorted(skill_names)}, task_types={sorted(task_types)}"
        )


_assert_registry_alignment()
